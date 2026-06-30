"use client";

import { useEffect } from "react";
import eventBus, {
  HotShortEvent,
  EventPayload,
} from "@/engine/EventBus";

type EventCallback = (
  payload?: EventPayload
) => void;

export default function useEvent(
  event: HotShortEvent,
  callback: EventCallback
) {
  useEffect(() => {
    const unsubscribe = eventBus.on(
      event,
      callback
    );

    return unsubscribe;
  }, [event, callback]);
}