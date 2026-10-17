"""Judge: one Jev call per view pair, bounded concurrency, per-view failures kept (U18)."""

import asyncio
import logging
from collections.abc import Callable

from pydantic import ValidationError
from typesafe_sdk import Image

from buyer_agent.config import Settings
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.images import normalise_png
from buyer_agent.jev_client import JevAnswer, JevClient, map_jev_error
from buyer_agent.jev_prompts import CONTEXT_V2, QUESTIONS_V2, VIEW_QUESTION_IDS
from buyer_agent.models import JevViewScores, ViewFailure, ViewPair, unique_labels

log = logging.getLogger(__name__)
OnRaw = Callable[[str, JevAnswer], None]
OnFailure = Callable[[str, str, str], None]  # label, error code, detail (run log only)


def parse_scores(label: str, answer: JevAnswer) -> JevViewScores:
    try:
        return JevViewScores(
            view=label,
            model=answer.model,
            latency_ms=answer.latency_ms,
            **{q: answer.nouls[q] for q in VIEW_QUESTION_IDS},
        )
    except (KeyError, ValidationError, TypeError) as exc:
        raise AgentError(ErrorCode.JEV_BAD_RESPONSE, f"bad scores for {label}") from exc


async def _score(
    client: JevClient,
    pair: ViewPair,
    key: str,
    sem: asyncio.Semaphore,
    settings: Settings,
    on_raw: OnRaw,
) -> JevViewScores:
    png_a, png_b = normalise_png(pair.png_a), normalise_png(pair.png_b)  # before any call
    state = {
        "context": CONTEXT_V2,
        "view": pair.label,
        "model_a": Image(png_a),
        "model_b": Image(png_b),
    }
    async with sem:
        try:
            answer = await asyncio.wait_for(
                client.ask(state, QUESTIONS_V2, key=key), settings.jev_wait_for_s
            )
        except AgentError:
            raise
        except Exception as exc:
            raise map_jev_error(exc) from exc
    on_raw(pair.label, answer)
    return parse_scores(pair.label, answer)


async def _view(
    client: JevClient,
    pair: ViewPair,
    key: str,
    sem: asyncio.Semaphore,
    settings: Settings,
    on_raw: OnRaw,
    on_failure: OnFailure,
) -> JevViewScores | ViewFailure:
    try:
        return await _score(client, pair, key, sem, settings, on_raw)
    except AgentError as err:
        if err.code is ErrorCode.JEV_AUTH:
            raise
        code, detail = err.code, err.detail
    except Exception as exc:  # noqa: BLE001 one bad view must not sink the rest
        code, detail = ErrorCode.INTERNAL, type(exc).__name__
    on_failure(pair.label, code.value, detail)
    return ViewFailure(view=pair.label, code=code.value)


async def judge_views(
    client: JevClient,
    pairs: list[ViewPair],
    settings: Settings,
    on_raw: OnRaw,
    on_failure: OnFailure,
) -> tuple[list[JevViewScores], list[ViewFailure]]:
    unique_labels(p.label for p in pairs)
    sem = asyncio.Semaphore(settings.concurrency)
    tasks = [
        asyncio.ensure_future(_view(client, p, f"view-{i:02d}", sem, settings, on_raw, on_failure))
        for i, p in enumerate(pairs)
    ]
    done, pending = await asyncio.wait(
        tasks, timeout=settings.judge_stage_cap_s, return_when=asyncio.FIRST_EXCEPTION
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            raise task.exception()  # only JEV_AUTH escapes _view
    scores: list[JevViewScores] = []
    failures: list[ViewFailure] = []
    for pair, task in zip(pairs, tasks, strict=True):
        result = task.result() if task in done else None
        if result is None:  # stage cap hit
            on_failure(pair.label, ErrorCode.JEV_TIMEOUT.value, "judge stage cap")
            result = ViewFailure(view=pair.label, code=ErrorCode.JEV_TIMEOUT.value)
        (scores if isinstance(result, JevViewScores) else failures).append(result)
    return scores, failures
