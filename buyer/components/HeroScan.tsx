"use client";
// The landing's shop window (docs/design/DESIGN.md §1): a real Mint scan you can turn. The files are the real
// end-to-end run in buyer/public/demo/listings/a6816dfc (phone upload -> splat -> listing agent), so this is shown in
// live mode too, and the caption says exactly what it is.
import SplatViewer from "./SplatViewer";

const SCAN = "/demo/listings/a6816dfc";

export default function HeroScan() {
  return (
    <figure className="flex flex-col gap-3">
      <div className="aspect-[4/3.4] w-full overflow-hidden rounded-[28px] bg-surface md:aspect-square">
        <SplatViewer
          src={`${SCAN}/splat.spz`}
          poster={`${SCAN}/spin/f00.webp`}
          label="A real Mint scan of a black ThinkPad mouse"
          autoRotate
          interactive
          className="bg-surface"
        />
      </div>
      <figcaption className="text-sm text-ink-2">
        A real Mint scan of a ThinkPad mouse, made from a phone video in about 40 seconds.
      </figcaption>
    </figure>
  );
}
