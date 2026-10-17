import { Children, type ReactNode } from "react";

// 2 cols <600, 3 at 600+, 4 at 1024+, 5 at 1440+ (DESIGN.md grid).
export default function ListingGrid({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <ul
      aria-label={label}
      className="grid list-none grid-cols-2 gap-4 p-0 min-[600px]:grid-cols-3 min-[1024px]:grid-cols-4 min-[1024px]:gap-6 min-[1440px]:grid-cols-5"
    >
      {Children.map(children, (c) => (
        <li>{c}</li>
      ))}
    </ul>
  );
}
