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

interface ChatFilterProps {
  doctors?: string[];
  doctorFilter: string;
  onDoctorChange: (value: string) => void;

  doctorTypes?: string[];
  doctorTypeFilter: string;
  onDoctorTypeChange: (value: string) => void;

  dateRange?: DateRange;
  onDateRangeChange: (range: DateRange | undefined) => void;
}

export function ChatFilter({
  doctors = [],
  doctorFilter,
  onDoctorChange,
  doctorTypes = [],
  doctorTypeFilter,
  onDoctorTypeChange,
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

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* 1. Filter by Doctor */}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              className="h-10 w-56 justify-between gap-2 bg-white font-normal text-gray-700 hover:bg-gray-50 border-gray-200 text-sm shadow-none focus-visible:ring-0 focus:ring-0 focus-visible:outline-none"
            />
          }
        >
          <div className="flex items-center gap-2 truncate">
            <RiUserLine className="w-4 h-4 shrink-0 text-gray-500" />
            <span className="truncate">
              {doctorFilter === "ALL" ? "Filter by doctor" : doctorFilter}
            </span>
          </div>
          <RiArrowDownSLine className="w-4 h-4 shrink-0 text-gray-400" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56 max-h-64 overflow-y-auto bg-white border border-gray-200 shadow-none rounded-md ring-0 outline-none">
          <DropdownMenuRadioGroup value={doctorFilter} onValueChange={onDoctorChange}>
            <DropdownMenuRadioItem closeOnClick value="ALL">
              All Doctors
            </DropdownMenuRadioItem>
            {doctors.map((doctor) => (
              <DropdownMenuRadioItem closeOnClick key={doctor} value={doctor}>
                {doctor}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 2. Filter by Doctor Type */}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              className="h-10 w-56 justify-between gap-2 bg-white font-normal text-gray-700 hover:bg-gray-50 border-gray-200 text-sm shadow-none focus-visible:ring-0 focus:ring-0 focus-visible:outline-none"
            />
          }
        >
          <div className="flex items-center gap-2 truncate">
            <RiMedicineBottleLine className="w-4 h-4 shrink-0 text-gray-500" />
            <span className="truncate">
              {doctorTypeFilter === "ALL" ? "Filter by doctor type" : doctorTypeFilter}
            </span>
          </div>
          <RiArrowDownSLine className="w-4 h-4 shrink-0 text-gray-400" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56 max-h-64 overflow-y-auto bg-white border border-gray-200 shadow-none rounded-md ring-0 outline-none">
          <DropdownMenuRadioGroup value={doctorTypeFilter} onValueChange={onDoctorTypeChange}>
            <DropdownMenuRadioItem closeOnClick value="ALL">
              All Doctor Types
            </DropdownMenuRadioItem>
            {doctorTypes.map((type) => (
              <DropdownMenuRadioItem closeOnClick key={type} value={type}>
                {type}
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
              className="h-10 w-64 justify-between gap-2 bg-white font-normal text-gray-700 hover:bg-gray-50 border-gray-200 text-sm shadow-none focus-visible:ring-0 focus:ring-0 focus-visible:outline-none"
            />
          }
        >
          <div className="flex items-center gap-2 truncate">
            <RiCalendarLine className="w-4 h-4 shrink-0 text-gray-500" />
            <span className="truncate">
              {formattedDateRange || "Filter by date range"}
            </span>
          </div>
          {formattedDateRange ? (
            <span
              role="button"
              tabIndex={0}
              className="p-0.5 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-600 shrink-0"
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
            <RiArrowDownSLine className="w-4 h-4 shrink-0 text-gray-400" />
          )}
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto min-w-70 p-2 bg-white border border-gray-200 shadow-none rounded-md ring-0 outline-none">
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


