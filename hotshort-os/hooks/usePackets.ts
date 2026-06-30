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
    return packetEngine.subscribe(setPackets);
  }, []);

  return {
    packets,

    spawn: packetEngine.spawn.bind(packetEngine),

    clear: packetEngine.clear.bind(packetEngine),
  };
}