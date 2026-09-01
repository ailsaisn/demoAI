"use client";

import { useMemo, useState } from "react";
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
	const { data: allUsers } = useUsers();
	const [userFilter, setUserFilter] = useState("ALL");
	const [chatTypeFilter, setChatTypeFilter] = useState("ALL");
	const [dateRange, setDateRange] = useState<DateRange | undefined>(undefined);
	const [searchQuery, setSearchQuery] = useState("");

	// Combine all registered users and users from chat histories
	const users = useMemo(() => {
		const userSet = new Set<string>();
		allUsers?.forEach((u) => {
			if (u.name) userSet.add(u.name);
		});
		chatHistories?.forEach((h) => {
			const name = h.user_name || h.doctor;
			if (name && name !== "Unknown") userSet.add(name);
		});
		return Array.from(userSet).sort();
	}, [allUsers, chatHistories]);

	// Build chat type options (General Prompt + unique Doctor Types)
	const chatTypes = useMemo(() => {
		const list: { value: string; label: string }[] = [
			{ value: "GENERAL_ASSISTANT", label: "General Prompt (Staff)" },
		];
		const doctorTypesSet = new Set<string>();
		allUsers?.forEach((u) => {
			if (u.dr_type) doctorTypesSet.add(u.dr_type);
		});
		chatHistories?.forEach((h) => {
			if (h.doctor_type) doctorTypesSet.add(h.doctor_type);
		});

		doctorTypesSet.forEach((dt) => {
			list.push({ value: dt, label: `Doctor - ${dt}` });
		});

		return list;
	}, [allUsers, chatHistories]);

	const filteredData = chatHistories?.filter((item) => {
		if (item.messages === 0 && !item.query) return false;

		// Filter by User
		if (userFilter !== "ALL") {
			const itemName = item.user_name || item.doctor;
			if (itemName !== userFilter) return false;
		}

		// Filter by Chat / Doctor Type
		if (chatTypeFilter !== "ALL") {
			if (chatTypeFilter === "GENERAL_ASSISTANT") {
				const isGeneral =
					item.session_type === "GENERAL_ASSISTANT" ||
					(!item.branch_id && item.branch === "General Assistant") ||
					item.user_type === "STAFF";
				if (!isGeneral) return false;
			} else {
				if (!item.doctor_type || item.doctor_type !== chatTypeFilter) return false;
			}
		}

		// Filter by Date Range
		if (dateRange?.from) {
			const itemDate = new Date(item.created_at);
			const fromDate = new Date(dateRange.from);
			fromDate.setHours(0, 0, 0, 0);
			if (itemDate < fromDate) return false;

			const toDate = dateRange.to ? new Date(dateRange.to) : new Date(dateRange.from);
			toDate.setHours(23, 59, 59, 999);
			if (itemDate > toDate) return false;
		}

		// Search Query
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase();
			const matchDoctor = item.doctor?.toLowerCase().includes(q);
			const matchUserName = item.user_name?.toLowerCase().includes(q);
			const matchQuery = item.query?.toLowerCase().includes(q);
			const matchSummary = item.summary?.toLowerCase().includes(q);
			const matchBranch = item.branch?.toLowerCase().includes(q);
			const matchType = item.session_type?.toLowerCase().includes(q);
			if (!matchDoctor && !matchUserName && !matchQuery && !matchSummary && !matchBranch && !matchType) {
				return false;
			}
		}
		return true;
	});

	return (
		<div className="flex flex-col min-h-full gap-6 p-6 pb-12">
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
						users={users} 
						userFilter={userFilter}
						onUserChange={setUserFilter}
						chatTypes={chatTypes}
						chatTypeFilter={chatTypeFilter}
						onChatTypeChange={setChatTypeFilter}
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
