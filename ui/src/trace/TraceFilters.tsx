import type { Dispatch, SetStateAction } from "react";

import { filterTypes, type FilterType } from "./helpers";

export function TraceFilters({
  filters,
  onChange,
}: {
  filters: Record<FilterType, boolean>;
  onChange: Dispatch<SetStateAction<Record<FilterType, boolean>>>;
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
    </div>
  );
}
