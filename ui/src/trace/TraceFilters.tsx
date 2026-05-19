import type { Dispatch, SetStateAction } from "react";

import { filterTypes, type FilterType } from "./helpers";

export function TraceFilters({
  filters,
  onChange,
  showImages,
  onToggleImages,
}: {
  filters: Record<FilterType, boolean>;
  onChange: Dispatch<SetStateAction<Record<FilterType, boolean>>>;
  showImages: boolean;
  onToggleImages: (v: boolean) => void;
}) {
  return (
    <div className="trace-filters" aria-label="Trace event filters">
      {filterTypes.map((type) => (
        <label key={type} className={filters[type] ? "selected" : ""}>
          <input
            type="checkbox"
            checked={filters[type]}
            onChange={(event) => {
              const checked = event.currentTarget.checked;
              onChange((current) => ({ ...current, [type]: checked }));
            }}
          />
          {type}
        </label>
      ))}
      <label className={`trace-filter-divider ${showImages ? "selected" : ""}`}>
        <input
          type="checkbox"
          checked={showImages}
          onChange={(e) => onToggleImages(e.currentTarget.checked)}
        />
        screenshots
      </label>
    </div>
  );
}
