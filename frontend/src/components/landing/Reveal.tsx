"use client";

import { useEffect } from "react";

/**
 * Plays the entrance animation of every element marked `data-reveal` when it scrolls into view.
 * Variants and timings live in globals.css ("Reveal on scroll"); `--d` on an element staggers it.
 * Elements already on screen at load animate straight away.
 */
export function RevealOnScroll() {
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>("[data-reveal]:not(.is-in)");
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  return null;
}
