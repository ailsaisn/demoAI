"use client";

import {
	RiAlertLine,
	RiArrowDownSLine,
	RiBuildingLine,
	RiChat1Line,
	RiCheckDoubleLine,
	RiCheckLine,
	RiFilterOffLine,
	RiMedicineBottleLine,
	RiNotification3Line,
	RiUserLine,
} from "@remixicon/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuRadioGroup,
	DropdownMenuRadioItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/axios";
import { cn } from "@/lib/utils";

import { DataTablePagination } from "@/components/shared/data-table-pagination";
import { usePagination } from "@/hooks/use-pagination";
import { chatHistoryKeys } from "../chat-history/api/keys";
import { NOTIFICATION_KEYS } from "./api/keys";
import { FeedbackNotification } from "./api/types";

type FilterTab = "all" | "unread" | "read";

export default function NotificationsPage() {
	const [activeTab, setActiveTab] = useState<FilterTab>("all");
	const [doctorFilter, setDoctorFilter] = useState<string>("ALL");
	const [doctorTypeFilter, setDoctorTypeFilter] = useState<string>("ALL");
	const queryClient = useQueryClient();

	const { data: feedbacks = [], isLoading } = useQuery<FeedbackNotification[]>({
		queryKey: NOTIFICATION_KEYS.lists(),
		queryFn: async () => {
			const res = await api.get("/chats/feedback");
			return res.data;
		},
	});

	const markAsReadMutation = useMutation({
		mutationFn: async (sessionIds: string[]) => {
			await api.put("/chats/feedback/read", { session_ids: sessionIds });
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: NOTIFICATION_KEYS.all });
			queryClient.invalidateQueries({ queryKey: chatHistoryKeys.all });
		},
	});

	// Extract unique doctors and doctor types
	const doctors = useMemo(() => {
		const unique = new Set<string>();
		feedbacks.forEach((f) => {
			if (f.doctor && f.doctor !== "Unknown") {
				unique.add(f.doctor);
			}
		});
		return Array.from(unique);
	}, [feedbacks]);

	const doctorTypes = useMemo(() => {
		const unique = new Set<string>();
		feedbacks.forEach((f) => {
			if (f.doctor_type) {
				unique.add(f.doctor_type);
			}
		});
		return Array.from(unique);
	}, [feedbacks]);

	const unreadCount = useMemo(
		() => feedbacks.filter((f) => !f.is_feedback_read).length,
		[feedbacks],
	);

	const readCount = useMemo(() => feedbacks.filter((f) => f.is_feedback_read).length, [feedbacks]);

	const filteredFeedbacks = useMemo(() => {
		return feedbacks.filter((item) => {
			// Tab filter
			if (activeTab === "unread" && item.is_feedback_read) return false;
			if (activeTab === "read" && !item.is_feedback_read) return false;

			// Doctor filter
			if (doctorFilter !== "ALL" && item.doctor !== doctorFilter) return false;

			// Doctor type filter
			if (doctorTypeFilter !== "ALL" && item.doctor_type !== doctorTypeFilter) return false;

			return true;
		});
	}, [feedbacks, activeTab, doctorFilter, doctorTypeFilter]);

	const {
		page,
		pageSize,
		totalPages,
		totalItems,
		paginatedItems,
		setPage,
		setPageSize,
		startIndex,
		endIndex,
	} = usePagination({ items: filteredFeedbacks, initialPageSize: 10 });

	const hasActiveFilters = doctorFilter !== "ALL" || doctorTypeFilter !== "ALL";

	const handleResetDropdownFilters = () => {
		setDoctorFilter("ALL");
		setDoctorTypeFilter("ALL");
		setPage(1);
	};

	const handleMarkAllAsRead = () => {
		const unreadIds = feedbacks.filter((f) => !f.is_feedback_read).map((f) => f.id);
		if (unreadIds.length === 0) return;
		markAsReadMutation.mutate(unreadIds);
	};

	const handleMarkAsRead = (id: string) => {
		markAsReadMutation.mutate([id]);
	};

	const formatTimestamp = (dateString: string) => {
		try {
			return format(new Date(dateString), "MMM d, yyyy • h:mm a");
		} catch {
			return dateString;
		}
	};

	return (
		<div className="flex flex-col h-full gap-4 p-6">
			{/* Header */}
			<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
				<div className="flex flex-col gap-1">
					<div className="flex items-center gap-2">
						<h1 className="text-xl font-semibold text-foreground">Notifications</h1>
						{unreadCount > 0 && (
							<Badge
								variant="secondary"
								className="bg-amber-50 text-amber-800 border-amber-200 text-[11px] font-semibold px-1.5 py-0"
							>
								{unreadCount} unread
							</Badge>
						)}
					</div>
					<p className="text-sm text-muted-foreground">
						Reported missing data issues and doctor feedback across chat sessions.
					</p>
				</div>

				<Button
					variant="outline"
					className="h-9 px-3 text-xs sm:text-sm border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg font-medium self-start sm:self-auto shadow-none cursor-pointer gap-1.5"
					onClick={handleMarkAllAsRead}
					disabled={unreadCount === 0 || markAsReadMutation.isPending}
				>
					<RiCheckDoubleLine className="size-3.5 text-zinc-500" />
					Mark all as read
				</Button>
			</div>

			{/* Filter Toolbar */}
			<div className="flex flex-wrap items-center justify-between gap-2.5">
				{/* Left: Category Tabs */}
				<div className="flex items-center gap-1">
					<button
						type="button"
						onClick={() => setActiveTab("all")}
						className={cn(
							"px-2.5 py-1 rounded-lg text-xs font-medium transition-colors",
							activeTab === "all"
								? "bg-gray-100 text-gray-900 font-semibold"
								: "text-muted-foreground hover:text-foreground hover:bg-gray-50",
						)}
					>
						All ({feedbacks.length})
					</button>
					<button
						type="button"
						onClick={() => setActiveTab("unread")}
						className={cn(
							"px-2.5 py-1 rounded-lg text-xs font-medium transition-colors",
							activeTab === "unread"
								? "bg-gray-100 text-gray-900 font-semibold"
								: "text-muted-foreground hover:text-foreground hover:bg-gray-50",
						)}
					>
						Unread ({unreadCount})
					</button>
					<button
						type="button"
						onClick={() => setActiveTab("read")}
						className={cn(
							"px-2.5 py-1 rounded-lg text-xs font-medium transition-colors",
							activeTab === "read"
								? "bg-gray-100 text-gray-900 font-semibold"
								: "text-muted-foreground hover:text-foreground hover:bg-gray-50",
						)}
					>
						Read ({readCount})
					</button>
				</div>

				{/* Right: Dropdown Filters */}
				<div className="flex flex-wrap items-center gap-2">
					{/* Reset Filters button at the left */}
					{hasActiveFilters && (
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={handleResetDropdownFilters}
							className="text-xs text-red-600 hover:text-red-700 bg-white hover:bg-red-50 border-red-200 hover:border-red-300 rounded-lg cursor-pointer h-9 px-3 gap-1.5 shadow-none transition-colors"
						>
							<RiFilterOffLine className="size-3.5 text-red-500" />
							Reset
						</Button>
					)}

					{/* Doctor Filter */}
					<DropdownMenu>
						<DropdownMenuTrigger
							render={
								<Button
									variant="outline"
									className="h-9 min-w-36 max-w-52 justify-between gap-1.5 bg-white font-normal text-zinc-700 hover:bg-zinc-50 border-gray-200 text-xs rounded-lg shadow-none cursor-pointer"
								/>
							}
						>
							<div className="flex items-center gap-1.5 truncate">
								<RiUserLine className="size-3.5 shrink-0 text-zinc-500" />
								<span className="truncate">
									{doctorFilter === "ALL" ? "All Doctors" : doctorFilter}
								</span>
							</div>
							<RiArrowDownSLine className="size-3.5 shrink-0 text-zinc-400" />
						</DropdownMenuTrigger>
						<DropdownMenuContent
							align="end"
							className="w-52 max-h-56 overflow-y-auto bg-white border border-gray-200 text-xs rounded-lg shadow-none"
						>
							<DropdownMenuRadioGroup value={doctorFilter} onValueChange={setDoctorFilter}>
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

					{/* Doctor Type Filter */}
					<DropdownMenu>
						<DropdownMenuTrigger
							render={
								<Button
									variant="outline"
									className="h-9 min-w-36 max-w-52 justify-between gap-1.5 bg-white font-normal text-zinc-700 hover:bg-zinc-50 border-gray-200 text-xs rounded-lg shadow-none cursor-pointer"
								/>
							}
						>
							<div className="flex items-center gap-1.5 truncate">
								<RiMedicineBottleLine className="size-3.5 shrink-0 text-zinc-500" />
								<span className="truncate">
									{doctorTypeFilter === "ALL" ? "All Doctor Types" : doctorTypeFilter}
								</span>
							</div>
							<RiArrowDownSLine className="size-3.5 shrink-0 text-zinc-400" />
						</DropdownMenuTrigger>
						<DropdownMenuContent
							align="end"
							className="w-52 max-h-56 overflow-y-auto bg-white border border-gray-200 text-xs rounded-lg shadow-none"
						>
							<DropdownMenuRadioGroup value={doctorTypeFilter} onValueChange={setDoctorTypeFilter}>
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
				</div>
			</div>

			{/* Notifications List - Separate Compact Divs */}
			<div className="flex-1 overflow-y-auto">
				{isLoading ? (
					<div className="flex flex-col gap-2">
						{[...Array(4)].map((_, i) => (
							<div
								key={i}
								className="bg-white border border-gray-100 rounded-md p-3 flex items-start gap-3"
							>
								<Skeleton className="size-7 rounded-full shrink-0" />
								<div className="flex-1 space-y-1.5">
									<div className="flex items-center justify-between">
										<Skeleton className="h-3.5 w-32" />
										<Skeleton className="h-3 w-24" />
									</div>
									<Skeleton className="h-3 w-full" />
								</div>
							</div>
						))}
					</div>
				) : filteredFeedbacks.length === 0 ? (
					<div className="bg-white border border-gray-100 rounded-md flex flex-col items-center justify-center p-10 text-center">
						<div className="bg-gray-50 size-10 rounded-full flex items-center justify-center mb-2.5 text-muted-foreground">
							<RiNotification3Line className="size-5 text-gray-400" />
						</div>
						<h3 className="text-xs font-medium text-gray-900">
							{hasActiveFilters
								? "No matching notifications"
								: activeTab === "unread"
									? "No unread notifications"
									: activeTab === "read"
										? "No read notifications"
										: "No notifications"}
						</h3>
						<p className="text-[11px] text-muted-foreground mt-0.5 max-w-xs">
							{hasActiveFilters
								? "Try changing or resetting your doctor or doctor type filters."
								: activeTab === "unread"
									? "You are caught up with all reported data issues."
									: activeTab === "read"
										? "No read notifications found."
										: "Reported missing data issues from doctors will appear here."}
						</p>
					</div>
				) : (
					<div className="flex flex-col gap-2.5">
						{paginatedItems.map((item: FeedbackNotification) => {
							const isUnread = !item.is_feedback_read;

							return (
								<div
									key={item.id}
									className={cn(
										"border rounded-md p-3.5 flex flex-col gap-2.5 transition-all text-xs",
										isUnread
											? "bg-amber-50/40 border-amber-200 hover:border-amber-300"
											: "bg-white border-gray-200/80 hover:border-gray-300",
									)}
								>
									{/* Top Row: Doctor Info, Badges, Timestamp & Action */}
									<div className="flex items-center justify-between gap-2">
										<div className="flex items-center gap-2 flex-wrap">
											<span className="font-semibold text-gray-900">
												{item.doctor || "Unknown Doctor"}
											</span>

											{item.doctor_type && (
												<span className="inline-flex items-center text-[10px] font-medium text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">
													{item.doctor_type}
												</span>
											)}

											{item.has_data_issue && (
												<span className="inline-flex items-center gap-1 text-[10px] font-medium text-rose-700 bg-rose-50 px-1.5 py-0.5 rounded">
													<RiAlertLine className="size-2.5" />
													Missing Data
												</span>
											)}

											{isUnread && (
												<span className="size-1.5 rounded-full bg-amber-500 inline-block" />
											)}
										</div>

										<div className="flex items-center gap-2 shrink-0">
											<span className="text-[11px] text-muted-foreground">
												{formatTimestamp(item.updated_at)}
											</span>
											{isUnread && (
												<Button
													variant="ghost"
													size="sm"
													onClick={() => handleMarkAsRead(item.id)}
													className="h-6 px-1.5 text-[11px] text-amber-800 hover:text-amber-950 hover:bg-amber-100/70 font-medium"
													title="Mark as read"
												>
													<RiCheckLine className="size-3 mr-0.5" />
													Mark read
												</Button>
											)}
										</div>
									</div>

									{/* Middle Row: Feedback Message */}
									<div className="text-xs leading-relaxed">
										{item.feedback ? (
											<p
												className={
													isUnread ? "text-amber-950 font-normal" : "text-gray-700 font-normal"
												}
											>
												{item.feedback}
											</p>
										) : (
											<p className="text-muted-foreground italic text-[11px]">
												No written comment provided.
											</p>
										)}
									</div>

									{/* Bottom Row: Chat Session & Branch Metadata */}
									<div className="flex items-center gap-3 flex-wrap pt-0.5 text-[11px] text-gray-700">
										<span className="inline-flex items-center gap-1 font-medium text-gray-600">
											<RiBuildingLine className="size-3 text-gray-500" />
											{item.branch || "Unknown Branch"}
										</span>

										<Link
											href={`/dashboard/chat-history/${item.id}`}
											className="inline-flex items-center gap-1 text-gray-600 hover:text-gray-900 transition-colors cursor-pointer"
											title="View chat session details"
										>
											<RiChat1Line className="size-3 text-gray-500" />
											<span>Session:</span>
											<span className="font-mono font-medium text-gray-800 hover:text-black break-all">
												{item.id}
											</span>
										</Link>
									</div>
								</div>
							);
						})}

						<DataTablePagination
							page={page}
							pageSize={pageSize}
							totalPages={totalPages}
							totalItems={totalItems}
							startIndex={startIndex}
							endIndex={endIndex}
							onPageChange={setPage}
							onPageSizeChange={setPageSize}
							itemName="notifications"
						/>
					</div>
				)}
			</div>
		</div>
	);
}
