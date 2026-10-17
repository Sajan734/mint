import { FRAME_COUNT, PALETTE_NAMES, SHAPES, renderTurntableFrame, type PaletteName, type Shape } from "@/lib/turntable";

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return SHAPES.flatMap((shape) =>
    PALETTE_NAMES.flatMap((palette) => Array.from({ length: FRAME_COUNT }, (_, i) => ({ shape, palette, n: String(i) }))),
  );
}

export async function GET(_req: Request, ctx: { params: Promise<{ shape: string; palette: string; n: string }> }) {
  const { shape, palette, n } = await ctx.params;
  const i = Number(n);
  if (!SHAPES.includes(shape as Shape) || !PALETTE_NAMES.includes(palette as PaletteName) || !Number.isInteger(i) || i < 0 || i >= FRAME_COUNT) {
    return new Response("not found", { status: 404 });
  }
  return new Response(renderTurntableFrame(shape as Shape, palette as PaletteName, i), {
    headers: { "Content-Type": "image/svg+xml; charset=utf-8", "Cache-Control": "public, max-age=31536000, immutable" },
  });
}
