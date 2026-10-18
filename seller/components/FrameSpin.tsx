// The frame viewer MediaPanel (a twin file) shows when an item has no splat. Each app has its own: here Spin.
import Spin from "./Spin";

export default function FrameSpin({ frames, alt }: { frames: string[]; alt: string }) {
  return <Spin frames={frames} alt={alt} />;
}
