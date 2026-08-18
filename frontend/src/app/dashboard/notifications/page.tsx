"use client";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/axios";
import {
	RiCheckDoubleLine,
	RiErrorWarningFill,
	RiNotification3Line,
	RiThumbDownFill,
	RiThumbUpFill,
} from "@remixicon/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NOTIFICATION_KEYS } from "./api/keys";
import { FeedbackNotification } from "./api/types";

export default function NotificationsPage() {
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
			queryClient.invalidateQueries({ queryKey: NOTIFICATION_KEYS.lists() });
		},
	});

	const unreadFeedbacks = feedbacks.filter((f: FeedbackNotification) => !f.is_feedback_read);

	const handleMarkAllAsRead = () => {
		if (unreadFeedbacks.length === 0) return;
		markAsReadMutation.mutate(unreadFeedbacks.map((f: FeedbackNotification) => f.id));
	};

	const handleMarkAsRead = (id: string) => {
		markAsReadMutation.mutate([id]);
	};

	return (
		<div className="flex flex-col h-full gap-6 p-6">
			<div className="flex items-center justify-between">
				<div className="flex flex-col gap-1">
					<h1 className="text-xl font-semibold text-foreground">Notifications</h1>
					<p className="text-sm text-muted-foreground">
						Review feedback and reports submitted by doctors during chat sessions.
					</p>
				</div>
				<Button
					variant="outline"
					size="sm"
					className="h-9"
					onClick={handleMarkAllAsRead}
					disabled={unreadFeedbacks.length === 0 || markAsReadMutation.isPending}
				>
					<RiCheckDoubleLine className="size-4 mr-2" />
					Mark all as read
				</Button>
			</div>

			<div className="border border-gray-100 rounded-md bg-white overflow-hidden flex-1 flex flex-col">
				{isLoading ? (
					<div className="flex-1 flex items-center justify-center p-12 text-center">
						<div className="text-sm text-gray-500">Loading notifications...</div>
					</div>
				) : feedbacks.length === 0 ? (
					<div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
						<div className="bg-gray-50 h-16 w-16 rounded-full flex items-center justify-center mb-4">
							<RiNotification3Line className="size-8 text-gray-400" />
						</div>
						<h3 className="text-sm font-medium text-gray-900">No notifications</h3>
						<p className="text-sm text-gray-500 mt-1">
							You&apos;re all caught up! Check back later.
						</p>
					</div>
				) : (
					<div className="flex-1 overflow-y-auto">
						<div className="divide-y divide-gray-100">
							{feedbacks.map((feedback: FeedbackNotification) => (
								<div
									key={feedback.id}
									className={`p-4 flex gap-4 transition-colors ${feedback.is_feedback_read ? "bg-white" : "bg-blue-50/30"}`}
								>
									<div className="shrink-0 mt-1">
										{feedback.rating === "GOOD" ? (
											<div className="bg-green-100 text-green-600 p-2 rounded-full">
												<RiThumbUpFill className="size-5" />
											</div>
										) : feedback.rating === "BAD" ? (
											<div className="bg-red-100 text-red-600 p-2 rounded-full">
												<RiThumbDownFill className="size-5" />
											</div>
										) : (
											<div className="bg-gray-100 text-gray-600 p-2 rounded-full">
												<RiNotification3Line className="size-5" />
											</div>
										)}
									</div>
									<div className="flex-1 min-w-0">
										<div className="flex items-center justify-between mb-1">
											<h4 className="text-sm font-semibold text-gray-900">
												Feedback from {feedback.doctor || "Unknown Doctor"}
											</h4>
											<span className="text-xs text-gray-500">
												{new Date(feedback.updated_at).toLocaleDateString()}{" "}
												{new Date(feedback.updated_at).toLocaleTimeString()}
											</span>
										</div>
										<p className="text-sm text-gray-600 mb-2">
											{feedback.feedback || "No additional written feedback provided."}
										</p>
										{feedback.has_data_issue && (
											<div className="inline-flex items-center gap-1 text-xs font-medium text-red-700 bg-red-50 px-2.5 py-1 rounded-md mb-2">
												<RiErrorWarningFill className="size-3.5" />
												Reported Data Not Found Issue
											</div>
										)}
										<div className="flex items-center text-xs text-gray-400 mt-1">
											<span>Session ID: {feedback.id}</span>
											<span className="mx-2">•</span>
											<span>Branch: {feedback.branch || "Unknown Branch"}</span>
										</div>
									</div>
									<div className="shrink-0 flex flex-col justify-center">
										{!feedback.is_feedback_read && (
											<Button
												variant="ghost"
												size="sm"
												onClick={() => handleMarkAsRead(feedback.id)}
												className="text-blue-600 hover:text-blue-700 hover:bg-blue-50"
											>
												Mark read
											</Button>
										)}
									</div>
								</div>
							))}
						</div>
					</div>
				)}
			</div>
		</div>
	);
}
