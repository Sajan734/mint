import { describe, expect, it } from "vitest";
import { advanceOrder, canVerify, createOrder, nextStatus, timelineFor, verifyOrder } from "../lib/orders";
import type { Order } from "../lib/types";

const base = { id: "o1", item_id: "i1", created_at: "2026-10-17T00:00:00Z", price_cad: 40 };

describe("orders", () => {
  it("createOrder totals and starts reserved", () => {
    const m = createOrder({ ...base, method: "meetup", shipping_cad: 9 });
    expect(m).toMatchObject({ status: "reserved", shipping_cad: 0, total_cad: 40 });
    const s = createOrder({ ...base, method: "shipping", shipping_cad: 9 });
    expect(s).toMatchObject({ shipping_cad: 9, total_cad: 49 });
  });

  it("meetup flow reaches picked_up then verify", () => {
    let o: Order = createOrder({ ...base, method: "meetup" });
    const seen = [o.status];
    for (let i = 0; i < 3; i++) {
      o = advanceOrder(o);
      seen.push(o.status);
    }
    expect(seen).toEqual(["reserved", "confirmed", "picked_up", "picked_up"]);
    expect(canVerify(o)).toBe(true);
    expect(verifyOrder(o).status).toBe("verified");
  });

  it("shipping flow", () => {
    expect(nextStatus("shipping", "reserved")).toBe("paid");
    expect(nextStatus("shipping", "paid")).toBe("shipped");
    expect(nextStatus("shipping", "shipped")).toBe("delivered");
    expect(nextStatus("shipping", "delivered")).toBeNull();
  });

  it("cannot verify early, and updates are immutable", () => {
    const o = createOrder({ ...base, method: "shipping" });
    expect(verifyOrder(o)).toBe(o);
    const a = advanceOrder(o);
    expect(a).not.toBe(o);
    expect(o.status).toBe("reserved");
  });

  it("timelineFor marks states", () => {
    const t = timelineFor("meetup", "confirmed");
    expect(t.map((s) => s.state)).toEqual(["done", "current", "upcoming", "upcoming"]);
    expect(timelineFor("shipping", "verified").every((s) => s.state === "done")).toBe(true);
  });
});
