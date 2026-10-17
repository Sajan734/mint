"use client";
// The landing's shop window: a real 3D Gaussian splat you can turn. It is the camera listed on the site (itm_sony_a7),
// captured and shared on SuperSplat by veryos under CC BY 4.0, so the caption credits it and does not call it a Mint
// scan. Credits for every model: /about#credits.
import { HERO, heroFrame } from "@/lib/hero";
import SplatViewer from "./SplatViewer";


/** `src`: the camera listing's splat_url, which carries its orientation fragment (scripts/gen-mock.mjs ROT). */
export default function HeroScan({ src = HERO.splat }: { src?: string | null }) {
  return (
    <figure className="flex flex-col gap-3">
      <div className="aspect-[4/3.4] w-full overflow-hidden rounded-[28px] bg-surface md:aspect-square">
        <SplatViewer
          src={src ?? HERO.splat}
          poster={heroFrame(0)}
          label={`3D view of a ${HERO.title}`}
          autoRotate
          interactive
          className="bg-surface"
        />
      </div>
      <figcaption className="text-sm text-ink-2">
        A real 3D scan of the{" "}
        <a href={`/listing/${HERO.item}`} className="font-semibold text-mint-ink underline-offset-2 hover:underline">
          Sony Alpha 7 for sale here
        </a>
        , shared by veryos on SuperSplat (CC BY 4.0).
      </figcaption>
    </figure>
  );
}
