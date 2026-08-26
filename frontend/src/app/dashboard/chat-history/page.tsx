"use client";

import { useState } from "react";
import type { DateRange } from "react-day-picker";
import { SearchBar } from "@/components/shared/search-bar";
import { RiLoader4Line } from "@remixicon/react";
import { ChatFilter } from "./components/chat-filter";
import { ChatHistoryCard } from "./components/chat-history-card";
import { ChatHistorySummary } from "./components/chat-history-summary";
import { useChatHistories } from "./hooks/use-chat-history";
import { useUsers } from "@/app/dashboard/users/hooks/use-users";

export default function ChatHistoryPage() {
	const { data: chatHistories, isLoading, isError } = useChatHistories();
	const { data: allDoctors } = useUsers("DOCTOR");
	const [doctorFilter, setDoctorFilter] = useState("ALL");
	const [doctorTypeFilter, setDoctorTypeFilter] = useState("ALL");
	const [dateRange, setDateRange] = useState<DateRange | undefined>(undefined);
	const [searchQuery, setSearchQuery] = useState("");

	// Get names of all registered doctors
	const doctors = allDoctors?.map((user) => user.name) || [];

	// Get unique doctor types
	const doctorTypes = Array.from(
		new Set(allDoctors?.map((u) => u.dr_type).filter(Boolean) as string[])
	);

	const filteredData = chatHistories?.filter((item) => {
		if (item.messages === 0 && !item.query) return false;
		if (doctorFilter !== "ALL" && item.doctor !== doctorFilter) return false;
		if (doctorTypeFilter !== "ALL") {
			if (!item.doctor_type || item.doctor_type !== doctorTypeFilter) return false;
		}
		if (dateRange?.from) {
			const itemDate = new Date(item.created_at);
			const fromDate = new Date(dateRange.from);
			fromDate.setHours(0, 0, 0, 0);
			if (itemDate < fromDate) return false;

			const toDate = dateRange.to ? new Date(dateRange.to) : new Date(dateRange.from);
			toDate.setHours(23, 59, 59, 999);
			if (itemDate > toDate) return false;
		}
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase();
			const matchDoctor = item.doctor?.toLowerCase().includes(q);
			const matchQuery = item.query?.toLowerCase().includes(q);
			const matchSummary = item.summary?.toLowerCase().includes(q);
			const matchBranch = item.branch?.toLowerCase().includes(q);
			if (!matchDoctor && !matchQuery && !matchSummary && !matchBranch) return false;
		}
		return true;
	});

	return (
		<div className="flex flex-col h-full gap-6 p-6">
			{/* Overview Summary Cards */}
			<ChatHistorySummary items={filteredData} />

			<div className="flex flex-col gap-4">
				{/* Toolbar */}
				<div className="flex flex-col xl:flex-row xl:items-center justify-between gap-3">
					<SearchBar
						containerClassName="max-w-md w-full"
						placeholder="Search for chat sessions..."
						value={searchQuery}
						onChange={(e) => setSearchQuery(e.target.value)}
					/>
					<ChatFilter 
						doctors={doctors} 
						doctorFilter={doctorFilter}
						onDoctorChange={setDoctorFilter}
						doctorTypes={doctorTypes}
						doctorTypeFilter={doctorTypeFilter}
						onDoctorTypeChange={setDoctorTypeFilter}
						dateRange={dateRange}
						onDateRangeChange={setDateRange}
					/>
				</div>

			{/* List */}
			<div className="flex flex-col gap-4">
				{isLoading && (
					<div className="flex items-center justify-center p-8 text-muted-foreground">
						<RiLoader4Line className="w-6 h-6 animate-spin" />
						<span className="ml-2">Loading chat histories...</span>
					</div>
				)}

				{isError && (
					<div className="p-4 text-sm text-red-500 bg-red-50 rounded-md">
						Failed to load chat history.
					</div>
				)}

				{!isLoading && !isError && filteredData?.length === 0 && (
					<div className="p-8 text-center text-muted-foreground">No chat history found.</div>
				)}

				{!isLoading &&
					!isError &&
					filteredData?.map((item) => <ChatHistoryCard key={item.id} item={item} />)}
			</div>
			</div>
		</div>
	);
}
