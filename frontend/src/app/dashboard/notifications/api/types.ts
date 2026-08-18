export interface FeedbackNotification {
	id: string;
	doctor: string;
	branch: string;
	rating: "GOOD" | "BAD" | null;
	feedback: string | null;
	has_data_issue: boolean;
	is_feedback_read: boolean;
	updated_at: string;
}
