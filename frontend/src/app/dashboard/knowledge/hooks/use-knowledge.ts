import { api } from "@/lib/axios";
import { getErrorMessage } from "@/lib/utils";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { knowledgeKeys, projectKeys } from "../api/keys";
import type { KnowledgeResponse, KnowledgeStatus, VisibilitySettings } from "../api/types";

export const useKnowledgeBaseList = () => {
	return useQuery({
		queryKey: knowledgeKeys.all,
		queryFn: async (): Promise<KnowledgeResponse[]> => {
			const response = await api.get("/knowledge/");
			return response.data;
		},
		refetchInterval: (query) => {
			const data = query.state.data;
			if (data?.some((item) => item.status === "PROCESSING")) {
				return 3000;
			}
			return false;
		},
	});
};

export const useKnowledgeDetail = (id: string) => {
	return useQuery({
		queryKey: knowledgeKeys.detail(id),
		queryFn: async (): Promise<KnowledgeResponse> => {
			const response = await api.get(`/knowledge/${id}`);
			return response.data;
		},
		enabled: !!id,
		refetchInterval: (query) => {
			const data = query.state.data;
			if (data?.status === "PROCESSING") {
				return 1500;
			}
			return false;
		},
	});
};

export const useKnowledgeBatch = (batchId: string) => {
	return useQuery({
		queryKey: ["knowledge-batch", batchId],
		queryFn: async (): Promise<KnowledgeResponse[]> => {
			const response = await api.get(`/knowledge/batch/${batchId}`);
			return response.data;
		},
		enabled: !!batchId,
		refetchInterval: (query) => {
			const data = query.state.data;
			if (data?.some((item) => item.status === "PROCESSING")) {
				return 2000;
			}
			return false;
		},
	});
};

export const useUploadKnowledge = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (formData: FormData) => {
			const response = await api.post("/knowledge/upload", formData);
			return response.data;
		},
		onSuccess: () => {
			toast.success("Files uploaded successfully!");
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to upload knowledge files."));
		},
	});
};

export const useUpdateKnowledgeStatus = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async ({ id, status }: { id: string; status: KnowledgeStatus }) => {
			const response = await api.patch(`/knowledge/${id}/status`, { status });
			return response.data;
		},
		onSuccess: (_, variables) => {
			toast.success("Status updated successfully!");
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
			if (variables?.id) {
				queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(variables.id) });
			}
			queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to update status."));
		},
	});
};

export const useApproveKnowledge = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (id: string) => {
			const response = await api.post(`/knowledge/${id}/approve`);
			return response.data;
		},
		onSuccess: (_, id) => {
			toast.success("Document approved and indexed into AI Knowledge Base!");
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(id) });
			queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to approve and index document."));
		},
	});
};

export const useApproveBatchKnowledge = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (batchId: string) => {
			const response = await api.post(`/knowledge/batch/${batchId}/approve`);
			return response.data;
		},
		onSuccess: () => {
			toast.success("All documents approved and indexed into AI Knowledge Base!");
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
			queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to approve batch documents."));
		},
	});
};

export const useDeleteKnowledge = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (param: string | { id: string; hideToast?: boolean }) => {
			const id = typeof param === "string" ? param : param.id;
			const hideToast = typeof param === "string" ? false : !!param.hideToast;
			const response = await api.delete(`/knowledge/${id}`);
			return { data: response.data, hideToast };
		},
		onSuccess: (result) => {
			if (!result?.hideToast) {
				toast.success("Knowledge deleted successfully!");
			}
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
			queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to delete knowledge document."));
		},
	});
};

export const useEditKnowledge = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async ({ id, data, hideToast }: { id: string; data: { summary: string; categories: string[]; visibility_settings?: VisibilitySettings; title?: string }; hideToast?: boolean }) => {
			const response = await api.put(`/knowledge/${id}`, data);
			return { data: response.data, hideToast };
		},
		onSuccess: (result, variables) => {
			if (!result.hideToast) {
				toast.success("Document updated successfully!");
			}
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(variables.id) });
			queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to update document."));
		},
	});
};

export const useIngestionQuota = () => {
	return useQuery({
		queryKey: ["knowledge-ingestion-quota"],
		queryFn: async (): Promise<{
			year_month: string;
			tokens_used: number;
			input_tokens: number;
			output_tokens: number;
			token_limit: number;
			percentage: number;
			documents_count: number;
			warning: boolean;
			exceeded: boolean;
		}> => {
			const response = await api.get("/knowledge/quota");
			return response.data;
		},
	});
};

export const useUpdateKnowledgeProject = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async ({
			knowledgeId,
			projectId,
			hideToast,
		}: {
			knowledgeId: string;
			projectId: string | null;
			hideToast?: boolean;
		}) => {
			const response = await api.put(`/knowledge/${knowledgeId}/project`, {
				project_id: projectId,
			});
			return { data: response.data, hideToast };
		},
		onSuccess: (result) => {
			if (!result?.hideToast) {
				toast.success("Knowledge project updated successfully!");
			}
			queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
			queryClient.invalidateQueries({ queryKey: projectKeys.all });
			queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to update project assignment."));
		},
	});
};

export interface QueryGeneralPayload {
	prompt: string;
	history?: Array<{ role: string; content: string }>;
}

export interface QueryGeneralResult {
	prompt: string;
	answer: string;
	action: "read" | "edit_applied" | "delete_applied" | string;
	target_knowledge_id?: string | null;
	total_found: number;
	results: Array<Record<string, unknown>>;
}

export const useQueryGeneral = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (payload: QueryGeneralPayload): Promise<QueryGeneralResult> => {
			const response = await api.post("/knowledge/query-general", payload);
			return response.data;
		},
		onSuccess: (data) => {
			if (data.action === "edit_applied" || data.action === "delete_applied") {
				queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
				if (data.target_knowledge_id) {
					queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(data.target_knowledge_id) });
				}
			}
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to execute knowledge query."));
		},
	});
};

export interface GeneralChatMessageItem {
	id: string;
	role: string;
	content: string;
	action?: string | null;
	target_knowledge_id?: string | null;
	total_found?: number | null;
	attachments?: Record<string, unknown> | null;
	created_at: string;
}

export interface GeneralChatSessionResponse {
	id: string;
	user_id: string;
	session_type: string;
	status: string;
	messages: GeneralChatMessageItem[];
	created_at: string;
	updated_at: string;
}

export const useGeneralChatSession = (sessionId?: string | null) => {
	return useQuery({
		queryKey: ["general-session", sessionId],
		queryFn: async (): Promise<GeneralChatSessionResponse> => {
			const response = await api.get(`/knowledge/general-session/${sessionId}`);
			return response.data;
		},
		enabled: !!sessionId,
	});
};

export const useCreateGeneralChatSession = () => {
	return useMutation({
		mutationFn: async (): Promise<GeneralChatSessionResponse> => {
			const response = await api.post("/knowledge/general-session");
			return response.data;
		},
	});
};

export const useSendGeneralChatMessage = (sessionId?: string | null) => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (payload: { prompt: string; attachments?: Record<string, unknown> }): Promise<GeneralChatSessionResponse> => {
			const response = await api.post(`/knowledge/general-session/${sessionId}/messages`, payload);
			return response.data;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(["general-session", sessionId], data);
			const latestMsg = data.messages[data.messages.length - 1];
			if (latestMsg?.action === "edit_applied" || latestMsg?.action === "delete_applied") {
				queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
				if (latestMsg.target_knowledge_id) {
					queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(latestMsg.target_knowledge_id) });
				}
			}
		},
		onError: (error: unknown) => {
			toast.error(getErrorMessage(error, "Failed to send message."));
		},
	});
};
