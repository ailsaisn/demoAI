"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";
import { chatHistoryKeys } from "../chat-history/api/keys";
import { branchKeys } from "../configuration/api/keys";
import { NOTIFICATION_KEYS } from "../notifications/api/keys";
import { userKeys } from "../users/api/keys";

export function useCisSyncListener() {
	const queryClient = useQueryClient();

	useEffect(() => {
		// Use absolute URL targeting the Next.js API proxy or directly the backend if configured that way.
		// Since NEXT_PUBLIC_API_URL is typically 'http://localhost:8000/api', we will construct it:
		const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

		const eventSource = new EventSource(`${apiUrl}/events/sync`);

		eventSource.onmessage = (event) => {
			if (event.data === "sync_completed") {
				// Invalidate the relevant queries to instantly trigger a refetch
				queryClient.invalidateQueries({ queryKey: userKeys.all });
				queryClient.invalidateQueries({ queryKey: branchKeys.lists() });
				queryClient.invalidateQueries({ queryKey: chatHistoryKeys.all });
				toast.info("Data refreshed from CIS sync.");
			} else if (event.data === "feedback_submitted") {
				queryClient.invalidateQueries({ queryKey: NOTIFICATION_KEYS.all });
				queryClient.invalidateQueries({ queryKey: chatHistoryKeys.all });
				toast.info("New feedback received.");
			} else {
				try {
					const parsed = JSON.parse(event.data);
					if (parsed.event_type === "KNOWLEDGE_NOT_FOUND") {
						queryClient.invalidateQueries({ queryKey: NOTIFICATION_KEYS.all });
						queryClient.invalidateQueries({ queryKey: chatHistoryKeys.all });
					}
				} catch {
					// Ignore non-json messages
				}
			}
		};

		eventSource.onerror = (err) => {
			console.error("SSE connection error", err);
			// The EventSource will automatically try to reconnect.
		};

		return () => {
			eventSource.close();
		};
	}, [queryClient]);
}
