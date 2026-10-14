import { SemanticBloom } from "./SemanticBloom";
import "../threeui.css";

export function Scene() {
  return (
    <div className="shader-frame">
      <SemanticBloom
        mode="dark"
        text="DealerDesk"
        size={1.00}
        opacity={1.00}
      />
    </div>
  );
}
