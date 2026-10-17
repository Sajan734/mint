"use client";
import { Children, isValidElement, useEffect, useRef, useState, type ReactNode } from "react";

// 2 cols <640, 3 at 640+, 4 at 1024+ (docs/design/DESIGN.md §5: product-first, big pictures).
// pageSize: progressive "Show more" reveal; omit to render everything.
export default function ListingGrid({
  children,
  label,
  pageSize,
}: {
  children: ReactNode;
  label?: string;
  pageSize?: number;
}) {
  const all = Children.toArray(children);
  const [shown, setShown] = useState(pageSize ?? all.length);
  const list = useRef<HTMLUListElement>(null);
  const focusFrom = useRef<number | null>(null);
  const visible = all.slice(0, shown);
  const left = all.length - visible.length;

  useEffect(() => {
    if (focusFrom.current === null) return;
    list.current?.children[focusFrom.current]?.querySelector("a")?.focus({ preventScroll: true });
    focusFrom.current = null;
  }, [shown]);

  return (
    <>
      <ul
        ref={list}
        aria-label={label}
        className="grid list-none grid-cols-2 gap-x-3 gap-y-8 p-0 sm:grid-cols-3 sm:gap-x-5 lg:grid-cols-4 lg:gap-x-6 lg:gap-y-10"
      >
        {visible.map((c, i) => (
          <li key={isValidElement(c) ? c.key : i}>{c}</li>
        ))}
      </ul>
      {pageSize && all.length > pageSize && (
        <div className="flex flex-col items-center gap-2 pt-6">
          <p aria-live="polite" className="text-sm text-ink-2 tabular-nums">
            {visible.length} of {all.length}
          </p>
          {left > 0 && (
            <button
              type="button"
              className="btn-secondary min-w-48"
              onClick={() => {
                focusFrom.current = visible.length;
                setShown(shown + pageSize);
              }}
            >
              Show {Math.min(pageSize, left)} more
            </button>
          )}
        </div>
      )}
    </>
  );
}
