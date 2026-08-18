"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { userKeys } from "../users/api/keys";
import { branchKeys } from "../configuration/api/keys";

export function useCisSyncListener() {
	const queryClient = useQueryClient();

	useEffect(() => {
		// Use absolute URL targeting the Next.js API proxy or directly the backend if configured that way.
		// Since NEXT_PUBLIC_API_URL is typically 'http://localhost:8000/api', we will construct it:
		const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
		
		const eventSource = new EventSource(`${apiUrl}/events/sync`);

		eventSource.onmessage = (event) => {
			console.log("SSE Event Received:", event.data);
			if (event.data === "sync_completed") {
				// Invalidate the relevant queries to instantly trigger a refetch
				queryClient.invalidateQueries({ queryKey: userKeys.all });
				queryClient.invalidateQueries({ queryKey: branchKeys.lists() });
				toast.info("Data refreshed from CIS sync.");
			} else if (event.data === "feedback_submitted") {
				// We must import NOTIFICATION_KEYS from the right place, wait!
				// Since we might not have NOTIFICATION_KEYS imported, let's just use the exact array key
				queryClient.invalidateQueries({ queryKey: ["feedbacks", "list"] });
				toast.info("New feedback received.");
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
