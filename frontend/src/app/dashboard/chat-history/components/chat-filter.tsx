"use client";

import { useState } from "react";
import {
  RiUserLine,
  RiMedicineBottleLine,
  RiCalendarLine,
  RiCloseLine,
  RiArrowDownSLine,
} from "@remixicon/react";
import { format } from "date-fns";
import type { DateRange } from "react-day-picker";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface ChatTypeOption {
  value: string;
  label: string;
}

interface ChatFilterProps {
  users?: string[];
  userFilter: string;
  onUserChange: (value: string) => void;

  chatTypes?: ChatTypeOption[];
  chatTypeFilter: string;
  onChatTypeChange: (value: string) => void;

  dateRange?: DateRange;
  onDateRangeChange: (range: DateRange | undefined) => void;
}

export function ChatFilter({
  users = [],
  userFilter,
  onUserChange,
  chatTypes = [],
  chatTypeFilter,
  onChatTypeChange,
  dateRange,
  onDateRangeChange,
}: ChatFilterProps) {
  const [isCalendarOpen, setIsCalendarOpen] = useState(false);

  const formattedDateRange = dateRange?.from
    ? dateRange.to
      ? dateRange.from.getFullYear() === dateRange.to.getFullYear()
        ? `${format(dateRange.from, "d MMM")} - ${format(dateRange.to, "d MMM yyyy")}`
        : `${format(dateRange.from, "d MMM yy")} - ${format(dateRange.to, "d MMM yy")}`
      : format(dateRange.from, "d MMM yyyy")
    : null;

  const selectedChatTypeLabel =
    chatTypeFilter === "ALL"
      ? "Filter by type"
      : chatTypes.find((t) => t.value === chatTypeFilter)?.label || chatTypeFilter;

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* 1. Filter by User / Doctor */}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              className="h-10 w-56 justify-between gap-2 bg-white font-normal text-zinc-700 hover:bg-zinc-50 border-gray-200 text-sm rounded-lg shadow-none cursor-pointer"
            />
          }
        >
          <div className="flex items-center gap-2 truncate">
            <RiUserLine className="w-4 h-4 shrink-0 text-zinc-500" />
            <span className="truncate">
              {userFilter === "ALL" ? "Filter by user" : userFilter}
            </span>
          </div>
          <RiArrowDownSLine className="w-4 h-4 shrink-0 text-zinc-400" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56 max-h-64 overflow-y-auto bg-white border border-gray-200 shadow-none rounded-lg ring-0 outline-none">
          <DropdownMenuRadioGroup value={userFilter} onValueChange={onUserChange}>
            <DropdownMenuRadioItem closeOnClick value="ALL">
              All Users
            </DropdownMenuRadioItem>
            {users.map((user) => (
              <DropdownMenuRadioItem closeOnClick key={user} value={user}>
                {user}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 2. Filter by Chat / Doctor Type */}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              className="h-10 w-56 justify-between gap-2 bg-white font-normal text-zinc-700 hover:bg-zinc-50 border-gray-200 text-sm rounded-lg shadow-none cursor-pointer"
            />
          }
        >
          <div className="flex items-center gap-2 truncate">
            <RiMedicineBottleLine className="w-4 h-4 shrink-0 text-zinc-500" />
            <span className="truncate">{selectedChatTypeLabel}</span>
          </div>
          <RiArrowDownSLine className="w-4 h-4 shrink-0 text-zinc-400" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56 max-h-64 overflow-y-auto bg-white border border-gray-200 shadow-none rounded-lg ring-0 outline-none">
          <DropdownMenuRadioGroup value={chatTypeFilter} onValueChange={onChatTypeChange}>
            <DropdownMenuRadioItem closeOnClick value="ALL">
              All Chat Types
            </DropdownMenuRadioItem>
            {chatTypes.map((type) => (
              <DropdownMenuRadioItem closeOnClick key={type.value} value={type.value}>
                {type.label}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 3. Filter by Date Range */}
      <Popover open={isCalendarOpen} onOpenChange={setIsCalendarOpen}>
        <PopoverTrigger
          render={
            <Button
              variant="outline"
              className="h-10 w-64 justify-between gap-2 bg-white font-normal text-zinc-700 hover:bg-zinc-50 border-gray-200 text-sm rounded-lg shadow-none cursor-pointer"
            />
          }
        >
          <div className="flex items-center gap-2 truncate">
            <RiCalendarLine className="w-4 h-4 shrink-0 text-zinc-500" />
            <span className="truncate">
              {formattedDateRange || "Filter by date range"}
            </span>
          </div>
          {formattedDateRange ? (
            <span
              role="button"
              tabIndex={0}
              className="p-0.5 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-600 shrink-0 cursor-pointer"
              onClick={(e) => {
                e.stopPropagation();
                onDateRangeChange(undefined);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.stopPropagation();
                  onDateRangeChange(undefined);
                }
              }}
            >
              <RiCloseLine className="w-4 h-4" />
            </span>
          ) : (
            <RiArrowDownSLine className="w-4 h-4 shrink-0 text-zinc-400" />
          )}
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto min-w-70 p-2 bg-white border border-gray-200 shadow-none rounded-lg ring-0 outline-none">
          <Calendar
            mode="range"
            selected={dateRange}
            onSelect={(range) => {
              onDateRangeChange(range);
            }}
            numberOfMonths={1}
            autoFocus
          />
          {formattedDateRange && (
            <div className="p-2 border-t border-gray-100 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs text-gray-500 hover:text-gray-900 shadow-none focus-visible:ring-0"
                onClick={() => {
                  onDateRangeChange(undefined);
                  setIsCalendarOpen(false);
                }}
              >
                Reset Date Filter
              </Button>
            </div>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}


