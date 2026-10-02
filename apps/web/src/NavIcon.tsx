import type { ReactNode } from "react";

/** Small stroke icons for the navigation. Decorative: the button text is the name. */
export function NavIcon({ name }: { name: string }) {
  return (
    <svg className="nav-ico" viewBox="0 0 24 24" aria-hidden="true">
      {glyph(name)}
    </svg>
  );
}

function glyph(name: string): ReactNode {
  switch (name) {
    case "home":
      return <path d="M4 11 12 4l8 7v9a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z" />;
    case "quick":
      return (
        <>
          <rect x="4" y="4" width="16" height="16" rx="3" />
          <path d="M12 8v8M8 12h8" />
        </>
      );
    case "list":
      return (
        <>
          <path d="M9 7h11M9 12h11M9 17h11" />
          <circle cx="5" cy="7" r="1" data-fill="" />
          <circle cx="5" cy="12" r="1" data-fill="" />
          <circle cx="5" cy="17" r="1" data-fill="" />
        </>
      );
    case "star":
      return <path d="m12 3.2 2.5 5.1 5.6.8-4 4 1 5.5L12 16.1 6.9 18.6l1-5.5-4-4 5.6-.8z" />;
    case "check":
      return (
        <>
          <circle cx="12" cy="12" r="8" />
          <path d="m8.2 12.2 2.5 2.5 5-5.2" />
        </>
      );
    case "calendar":
      return (
        <>
          <rect x="4" y="5" width="16" height="15" rx="2" />
          <path d="M8 3.5v4M16 3.5v4M4 10h16" />
        </>
      );
    case "wallet":
      return (
        <>
          <rect x="3" y="7" width="18" height="12" rx="2" />
          <path d="M3 11h18" />
          <circle cx="16" cy="15" r="1" data-fill="" />
        </>
      );
    case "bars":
      return <path d="M5 19V10M12 19V5M19 19v-7" />;
    case "trend":
      return (
        <>
          <path d="M4 16.5 9 11l3.5 3L20 6.5" />
          <path d="M14 6.5h6v6" />
        </>
      );
    case "box":
      return (
        <>
          <path d="M4 8.5 12 4.5l8 4v9l-8 4-8-4z" />
          <path d="M12 12.5v9M4 8.5l8 4 8-4" />
        </>
      );
    case "sliders":
      return (
        <>
          <path d="M4 8h16M4 16h16" />
          <circle cx="9" cy="8" r="2" />
          <circle cx="15" cy="16" r="2" />
        </>
      );
    case "gear":
      return (
        <>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3.2v2.3M12 18.5v2.3M3.2 12h2.3M18.5 12h2.3M5.8 5.8l1.6 1.6M16.6 16.6l1.6 1.6M18.2 5.8l-1.6 1.6M7.4 16.6 5.8 18.2" />
        </>
      );
    case "person":
      return (
        <>
          <circle cx="12" cy="8" r="3" />
          <path d="M5.5 19.2c1.2-3.2 3.5-4.7 6.5-4.7s5.3 1.5 6.5 4.7" />
        </>
      );
    case "folder":
      return <path d="M4 7.5h6l2 2h8v8.5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z" />;
    case "tag":
      return (
        <>
          <path d="M3.5 12.2 12 3.7h7.5V11l-8.5 8.5z" />
          <circle cx="15.2" cy="8.2" r="1.1" data-fill="" />
        </>
      );
    case "coins":
      return (
        <>
          <ellipse cx="12" cy="7" rx="6.5" ry="2.4" />
          <path d="M5.5 7v4.5c0 1.3 2.9 2.4 6.5 2.4s6.5-1.1 6.5-2.4V7" />
          <path d="M5.5 11.5V16c0 1.3 2.9 2.4 6.5 2.4s6.5-1.1 6.5-2.4v-4.5" />
        </>
      );
    case "form":
      return (
        <>
          <rect x="4" y="3.5" width="16" height="17" rx="2" />
          <path d="M8 8.5h8M8 12.5h8M8 16.5h5" />
        </>
      );
    case "cash":
      return (
        <>
          <rect x="3" y="7" width="18" height="10" rx="2" />
          <circle cx="12" cy="12" r="2" />
        </>
      );
    case "bank":
      return (
        <>
          <path d="M4 10h16M12 4 4 10M12 4l8 6" />
          <path d="M6 10v7M10 10v7M14 10v7M18 10v7M4 17h16" />
        </>
      );
    case "card":
      return (
        <>
          <rect x="3" y="6" width="18" height="12" rx="2" />
          <path d="M3 10.5h18" />
        </>
      );
    case "lock":
      return (
        <>
          <rect x="6" y="10.5" width="12" height="8.5" rx="2" />
          <path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" />
        </>
      );
    case "loan":
      return (
        <>
          <path d="M7 17 17 7" />
          <path d="M9 7h8v8" />
        </>
      );
    case "gem":
      return <path d="M3.5 9h17l-2.2-4H5.7zM3.5 9 12 20l8.5-11" />;
    case "candles":
      return (
        <>
          <path d="M8 5v14M16 5v14" />
          <path d="M6 8h4v6H6zM14 10h4v6h-4z" />
        </>
      );
    case "account":
      return <rect x="7" y="4.5" width="10" height="15" rx="1.6" />;
    default:
      return <circle cx="12" cy="12" r="3" />;
  }
}
