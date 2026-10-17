import { describe, expect, it } from "vitest";
import { createOrder } from "../lib/orders";
import { EMPTY, KEY, mergeOrders, parseState, readState, toggleSaved, updateOrder, writeState } from "../lib/store";

const mem = (init: Record<string, string> = {}) => {
  const d = { ...init };
  return { d, getItem: (k: string) => d[k] ?? null, setItem: (k: string, v: string) => void (d[k] = v) };
};
const order = createOrder({ id: "o1", item_id: "i1", created_at: "t", method: "meetup", price_cad: 10 });

describe("store", () => {
  it("toggles saved ids", () => {
    const a = toggleSaved(EMPTY, "x");
    expect(a.saved).toEqual(["x"]);
    expect(toggleSaved(a, "x").saved).toEqual([]);
  });
  it("round-trips through storage under mint.v1", () => {
    const s = mem();
    writeState(s, { saved: ["x"], orders: [order] });
    expect(KEY).toBe("mint.v1");
    expect(readState(s)).toEqual({ saved: ["x"], orders: [order] });
  });
  it("survives corrupt, missing or wrong-shape storage", () => {
    expect(readState(mem())).toEqual(EMPTY);
    expect(readState(mem({ [KEY]: "{not json" }))).toEqual(EMPTY);
    expect(parseState('{"saved":[1],"orders":"no"}')).toEqual(EMPTY);
    expect(parseState(JSON.stringify({ saved: ["a", 2], orders: [{ id: 1 }, order] }))).toEqual({ saved: ["a"], orders: [order] });
    expect(() => writeState({ getItem: () => null, setItem: () => { throw new Error("full"); } }, EMPTY)).not.toThrow();
  });
  it("updates orders by id and merges seeds under stored", () => {
    const s = { saved: [], orders: [order] };
    expect(updateOrder(s, "o1", (o) => ({ ...o, status: "confirmed" })).orders[0].status).toBe("confirmed");
    const seed = { ...order, id: "seed", status: "paid" as const };
    const merged = mergeOrders([seed, { ...order, status: "reserved" }], [{ ...order, status: "confirmed" }]);
    expect(merged.map((o) => o.id)).toEqual(["seed", "o1"]);
    expect(merged[1].status).toBe("confirmed");
  });
});
