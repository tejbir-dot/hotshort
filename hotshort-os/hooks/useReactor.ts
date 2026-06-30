"use client";

import { useEffect, useState } from "react";
import reactorEngine, {
  ReactorState,
} from "@/engine/ReactorEngine";

export default function useReactor() {
  const [state, setState] = useState<ReactorState>(
    reactorEngine.getState()
  );

  useEffect(() => {
    return reactorEngine.subscribe(setState);
  }, []);

  return {
    ...state,

    pulse: reactorEngine.pulse.bind(reactorEngine),

    setEnergy:
      reactorEngine.setEnergy.bind(reactorEngine),

    setThinking:
      reactorEngine.setThinking.bind(reactorEngine),

    setTemperature:
      reactorEngine.setTemperature.bind(
        reactorEngine
      ),
  };
}