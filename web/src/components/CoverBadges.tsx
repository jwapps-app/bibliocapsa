import { Check } from "lucide-react";

/** Upper-right cover cluster: format dots (blue = also digital, amber = physical)
 *  plus the theme-colored "read" check. Single source for BookCard and ShelfGrid —
 *  the markup was previously duplicated and had already drifted (lost tooltips). */
export function CoverBadges({ isDual, isNative, isRead, location }: {
  isDual: boolean; isNative: boolean; isRead: boolean; location?: string | null;
}) {
  if (!isDual && !isNative && !isRead) return null;
  return (
    <div style={{ position: "absolute", top: "6px", right: "6px", display: "flex", gap: "4px", alignItems: "center", zIndex: 10 }}>
      {(isDual || isNative) && (
        <div style={{ display: "flex", gap: "3px", alignItems: "center" }}>
          {isDual && (
            <div title="Also owned as digital"
              style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#4a9aba",
                       boxShadow: "0 0 0 1px rgba(0,0,0,0.5), 0 0 4px rgba(74,154,186,0.8)" }} />
          )}
          <div title={location ? `Physical · ${location}` : "Physical copy"}
            style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#c9933a",
                     boxShadow: "0 0 0 1px rgba(0,0,0,0.5), 0 0 4px rgba(201,147,58,0.8)" }} />
        </div>
      )}
      {isRead && (
        <div title="Read"
          style={{ width: "17px", height: "17px", borderRadius: "50%", background: "var(--gold)",
                   display: "flex", alignItems: "center", justifyContent: "center",
                   boxShadow: "0 0 0 1px rgba(0,0,0,0.55)" }}>
          <Check style={{ width: "11px", height: "11px", color: "var(--ink)", strokeWidth: 3.5 }} />
        </div>
      )}
    </div>
  );
}
