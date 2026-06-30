"use client";

import { useEffect, useState } from "react";
import packetEngine, {
  Packet,
} from "@/engine/PacketEngine";

export default function usePackets() {
  const [packets, setPackets] = useState<Packet[]>(
    packetEngine.getPackets()
  );

  useEffect(() => {
    const unsubscribe = packetEngine.subscribe(setPackets);
    return () => {
      unsubscribe();
    };
  }, []);

  return {
    packets,

    spawn: packetEngine.spawn.bind(packetEngine),

    clear: packetEngine.clear.bind(packetEngine),
  };
}