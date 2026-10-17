import { describe, expect, it } from "vitest";
import { orderTotal, shippingFee, validateAddress, validateStep2 } from "@/components/ReserveSheet";

const ok = { name: "A B", street: "1 Main St", city: "Toronto", postal_code: "M5V 2T6" };

describe("ReserveSheet logic", () => {
  it("fee by size_class, default small", () => {
    expect(shippingFee({})).toBe(12);
    expect(shippingFee({ size_class: "small" })).toBe(12);
    expect(shippingFee({ size_class: "Large" })).toBe(25);
  });
  it("postal code validation", () => {
    expect(validateAddress(ok)).toEqual({});
    expect(validateAddress({ ...ok, postal_code: "m5v2t6" })).toEqual({});
    expect(validateAddress({ ...ok, postal_code: "12345" }).postal_code).toMatch(/Canadian/);
    expect(validateAddress({ ...ok, postal_code: "D5V 2T6" }).postal_code).toBeDefined();
  });
  it("requires all address fields", () => {
    const e = validateAddress({ name: "", street: " ", city: "", postal_code: "" });
    expect(Object.keys(e).sort()).toEqual(["city", "name", "postal_code", "street"]);
  });
  it("method choice drives validation and total", () => {
    expect(validateStep2("meetup", "", ok).slot).toBeDefined();
    expect(validateStep2("meetup", "2026-10-17T14:00:00Z", { ...ok, city: "" })).toEqual({});
    expect(validateStep2("shipping", "", { ...ok, city: "" }).city).toBeDefined();
    expect(orderTotal(45, "meetup", 12)).toBe(45);
    expect(orderTotal(45, "shipping", 12)).toBe(57);
  });
});
