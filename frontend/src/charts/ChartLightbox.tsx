import { useEffect, useState, type ReactNode } from "react";

interface ChartLightboxProps {
  children: ReactNode;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  buttonVisibility?: "always" | "expanded";
}

export default function ChartLightbox({
  children,
  expanded: controlledExpanded,
  onExpandedChange,
  buttonVisibility = "always",
}: ChartLightboxProps) {
  const [internalExpanded, setInternalExpanded] = useState(false);
  const expanded = controlledExpanded ?? internalExpanded;

  function setExpanded(next: boolean) {
    if (controlledExpanded === undefined) setInternalExpanded(next);
    onExpandedChange?.(next);
  }

  useEffect(() => {
    if (!expanded) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [expanded]);

  useEffect(() => {
    const resizeTimer = window.setTimeout(
      () => window.dispatchEvent(new Event("resize")),
      0,
    );
    return () => window.clearTimeout(resizeTimer);
  }, [expanded]);

  const showInlineButton =
    buttonVisibility === "always" ||
    (buttonVisibility === "expanded" && expanded);

  return (
    <>
      {expanded ? (
        <div
          className="chart-lightbox-backdrop"
          onClick={() => setExpanded(false)}
          aria-hidden="true"
        />
      ) : null}
      <div
        className={[
          "chart-lightbox",
          showInlineButton ? "chart-lightbox-has-button" : "",
          expanded ? "chart-lightbox-expanded" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {children}
        {showInlineButton ? (
          <button
            type="button"
            className="chart-lightbox-button"
            aria-label={expanded ? "关闭图表" : "放大图表"}
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "关闭" : "放大"}
          </button>
        ) : null}
      </div>
    </>
  );
}
