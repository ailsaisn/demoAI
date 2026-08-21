import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export function formatErrorDetail(detail: string): string {
	if (!detail) return detail;

	// Handle published duplicate document error
	if (detail.includes("sudah terpublikasi") || detail.includes("already published")) {
		const match = detail.match(/'([^']+)'/);
		const fileName = match ? match[1] : null;
		if (fileName) {
			return `Document '${fileName}' is already published in the active Knowledge Base. Use 'Edit Knowledge' to update it.`;
		}
		return "This document is already published in the active Knowledge Base. Use 'Edit Knowledge' to update it.";
	}

	// Handle draft duplicate in review queue error
	if (detail.includes("Draft peninjauan") || detail.includes("antrean On Review")) {
		const match = detail.match(/'([^']+)'/);
		const fileName = match ? match[1] : null;
		if (fileName) {
			return `A review draft for '${fileName}' already exists in On Review (Pending). Please review or delete the existing draft first.`;
		}
		return "A review draft for this document already exists in On Review (Pending).";
	}

	return detail;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getErrorMessage(error: any, defaultMessage = "An error occurred. Please try again."): string {
	if (!error) return defaultMessage;

	const detail = error.response?.data?.detail;

	if (typeof detail === "string") {
		return formatErrorDetail(detail);
	}

	if (Array.isArray(detail) && detail.length > 0 && detail[0].msg) {
		return formatErrorDetail(detail[0].msg);
	}

	return formatErrorDetail(error.message || defaultMessage);
}
