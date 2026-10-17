// The landing's hero item (components/HeroScan.tsx). Plain data, so server pages can use it too.
export const HERO = {
  item: "itm_sony_a7",
  splat: "https://d28zzqy0iyovbz.cloudfront.net/467df6a2/v1/meta.json#rx=180&ry=180",
  frames: "/demo/splats/sony-a7",
  title: "Sony Alpha 7 camera",
};
export const heroFrame = (n: number) => `${HERO.frames}/f${String(n % 24).padStart(2, "0")}.webp`;
