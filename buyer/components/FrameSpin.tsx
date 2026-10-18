// The frame viewer MediaPanel (a twin file) shows when an item has no splat. Each app has its own: here SpinViewer.
import SpinViewer from "./SpinViewer";

export default function FrameSpin({ frames, alt }: { frames: string[]; alt: string }) {
  return <SpinViewer frames={frames} alt={alt} variant="detail" />;
}
