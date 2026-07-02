"use client";

import { Mic } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface AIVoiceInputProps {
  onStart?: () => void;
  onStop?: (duration: number) => void;
  visualizerBars?: number;
  demoMode?: boolean;
  demoInterval?: number;
  className?: string;
  /**
   * Controlled mode: when `active` is passed the component stops driving its own
   * state and reflects the caller's recording session instead — `active` is the
   * on/off, `elapsedSeconds` the timer, `getLevels` feeds real mic amplitude into
   * the visualizer, and a click calls `onToggle`. Omit all of these for the
   * standalone/demo behavior.
   */
  active?: boolean;
  elapsedSeconds?: number;
  getLevels?: (bars: number) => number[] | null;
  statusText?: string;
  ariaLabel?: string;
  onToggle?: () => void;
}

export function AIVoiceInput({
  onStart,
  onStop,
  visualizerBars = 48,
  demoMode = false,
  demoInterval = 3000,
  className,
  active,
  elapsedSeconds,
  getLevels,
  statusText,
  ariaLabel,
  onToggle,
}: AIVoiceInputProps) {
  const [submitted, setSubmitted] = useState(false);
  const [time, setTime] = useState(0);
  const [barHeights, setBarHeights] = useState<number[]>([]);
  const [isDemo, setIsDemo] = useState(demoMode);

  const controlled = active !== undefined;
  const recording = controlled ? Boolean(active) : submitted;
  const displaySeconds = controlled ? Math.max(0, Math.floor(elapsedSeconds ?? 0)) : time;

  // Tick the elapsed timer only while recording (uncontrolled only — the caller
  // owns the clock in controlled mode).
  useEffect(() => {
    if (controlled || !submitted) return;
    onStart?.();
    const intervalId = setInterval(() => setTime((t) => t + 1), 1000);
    return () => clearInterval(intervalId);
  }, [controlled, submitted, onStart]);

  // Drive the visualizer from an interval so the randomness stays out of render
  // (lint purity + no SSR hydration mismatch — hence no `isClient` guard needed).
  // In controlled mode `getLevels` supplies real amplitude; otherwise animate.
  useEffect(() => {
    if (!recording) return;
    const tick = () => {
      const lv = getLevels?.(visualizerBars);
      if (lv && lv.length) {
        // Boost quiet speech into a visible range, clamp to the track height.
        setBarHeights(lv.map((v) => Math.max(8, Math.min(100, v * 140))));
      } else {
        setBarHeights(
          Array.from({ length: visualizerBars }, () => 20 + Math.random() * 80),
        );
      }
    };
    const intervalId = setInterval(tick, getLevels ? 60 : 150);
    return () => clearInterval(intervalId);
  }, [recording, visualizerBars, getLevels]);

  useEffect(() => {
    if (controlled || !isDemo) return;

    let timeoutId: NodeJS.Timeout;
    const runAnimation = () => {
      setSubmitted(true);
      timeoutId = setTimeout(() => {
        setSubmitted(false);
        timeoutId = setTimeout(runAnimation, 1000);
      }, demoInterval);
    };

    const initialTimeout = setTimeout(runAnimation, 100);
    return () => {
      clearTimeout(timeoutId);
      clearTimeout(initialTimeout);
    };
  }, [controlled, isDemo, demoInterval]);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const handleClick = () => {
    if (controlled) {
      onToggle?.();
      return;
    }
    if (isDemo) {
      setIsDemo(false);
      setSubmitted(false);
      return;
    }
    if (submitted) {
      setSubmitted(false);
      onStop?.(time);
      setTime(0);
    } else {
      setSubmitted(true);
    }
  };

  return (
    <div className={cn("w-full py-4", className)}>
      <div className="relative max-w-xl w-full mx-auto flex items-center flex-col gap-2">
        <button
          className={cn(
            "group w-16 h-16 rounded-xl flex items-center justify-center transition-colors",
            recording
              ? "bg-none"
              : "bg-none hover:bg-black/10 dark:hover:bg-white/10"
          )}
          type="button"
          aria-label={ariaLabel}
          onClick={handleClick}
        >
          {recording ? (
            <div
              className="w-6 h-6 rounded-sm animate-spin bg-black dark:bg-white cursor-pointer pointer-events-auto"
              style={{ animationDuration: "3s" }}
            />
          ) : (
            <Mic className="w-6 h-6 text-black/70 dark:text-white/70" />
          )}
        </button>

        <span
          className={cn(
            "font-mono text-sm transition-opacity duration-300",
            recording
              ? "text-black/70 dark:text-white/70"
              : "text-black/30 dark:text-white/30"
          )}
        >
          {formatTime(displaySeconds)}
        </span>

        <div className="h-4 w-64 flex items-center justify-center gap-0.5">
          {[...Array(visualizerBars)].map((_, i) => (
            <div
              key={i}
              className={cn(
                "w-0.5 rounded-full transition-all duration-300",
                recording
                  ? "bg-black/50 dark:bg-white/50"
                  : "bg-black/10 dark:bg-white/10 h-1"
              )}
              style={
                recording
                  ? {
                      height: `${barHeights[i] ?? 40}%`,
                    }
                  : undefined
              }
            />
          ))}
        </div>

        <p className="h-4 text-xs text-black/70 dark:text-white/70">
          {statusText ?? (recording ? "Listening..." : "Click to speak")}
        </p>
      </div>
    </div>
  );
}
