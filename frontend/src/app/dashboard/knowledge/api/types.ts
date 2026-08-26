export type KnowledgeType = "PRODUCT" | "TREATMENT" | "PROMOTIONAL" | "GENERAL" | "OTHER";
export type KnowledgeStatus = "PENDING" | "PROCESSING" | "APPROVED" | "REJECTED";

export interface KnowledgeCreate {
	title: string;
	content?: string | null;
	file_name: string;
	original_path: string;
	mime_type?: string | null;
	file_size?: number | null;
	type?: KnowledgeType;
	project_id?: string | null;
}

export interface VisibilitySettings {
	clinics: string[];
	doctor_types: string[];
	doctors: string[];
}

export interface KnowledgeResponse {
	id: string; // UUID
	title: string;
	content?: string | null;
	file_name: string;
	original_path: string;
	mime_type?: string | null;
	file_size?: number | null;
	type: KnowledgeType;
	status: KnowledgeStatus;
	ai_summary?: string | null;
	ai_confidence?: number | null;
	uploaded_by: string; // UUID
	approved_by?: string | null; // UUID
	project_id?: string | null; // UUID
	metadata?: {
		visibility_settings?: VisibilitySettings;
		[key: string]: unknown;
	} | null;
	created_at: string;
	updated_at: string;
}

export interface ProjectResponse {
	id: string; // UUID
	name: string;
	description?: string | null;
	created_by?: string | null;
	total_knowledges: number;
	created_at: string;
	updated_at: string;
}

export interface ProjectDetailResponse {
	id: string; // UUID
	name: string;
	description?: string | null;
	created_by?: string | null;
	total_knowledges: number;
	knowledges: KnowledgeResponse[];
	created_at: string;
	updated_at: string;
}

export interface ProjectStatsResponse {
	total_projects: number;
	total_knowledge: number;
}

export interface ProjectCreate {
	name: string;
	description?: string | null;
}

export interface ProjectUpdate {
	name?: string;
	description?: string | null;
}
