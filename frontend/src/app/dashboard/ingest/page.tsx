"use client";

import { PromptInput } from "./components/prompt-input";
import {
	RiFileTextLine,
	RiRobot2Line,
	RiAlertLine,
	RiGitRepositoryLine,
	RiGitMergeLine,
} from "@remixicon/react";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useEffect, useMemo, Suspense } from "react";
import { useUploadKnowledge, useIngestionQuota, useCreateGeneralChatSession } from "../knowledge/hooks/use-knowledge";
import { useProjects } from "../knowledge/hooks/use-projects";

function IngestContent() {
	const router = useRouter();
	const searchParams = useSearchParams();
	const projectId = searchParams.get("projectId") || searchParams.get("project_id");

	const { data: projects = [] } = useProjects();
	const uploadMutation = useUploadKnowledge();
	const { data: quota } = useIngestionQuota();

	const [mode, setMode] = useState<"ingest" | "general">("ingest");
	const [selectedProjectId, setSelectedProjectId] = useState<string>(projectId || "none");
	const [errorMsg, setErrorMsg] = useState<string | null>(null);
	const [promptValue, setPromptValue] = useState("");

	useEffect(() => {
		const timer = setTimeout(() => {
			if (projectId && projects.length > 0) {
				const exists = projects.some((p) => p.id === projectId);
				setSelectedProjectId(exists ? projectId : "none");
			}
		}, 0);
		return () => clearTimeout(timer);
	}, [projectId, projects]);

	const isGeneralMode = mode === "general";

	const selectedProjectName = useMemo(() => {
		if (!selectedProjectId || selectedProjectId === "none") {
			return "No Project";
		}
		const found = projects.find((p) => p.id === selectedProjectId);
		return found ? found.name : "Select Project";
	}, [selectedProjectId, projects]);

	const createGeneralSession = useCreateGeneralChatSession();

	const handleSend = (value: string, _category: string | undefined, files: File[]) => {
		setErrorMsg(null);

		if (isGeneralMode) {
			if (!value || !value.trim()) {
				setErrorMsg("Please enter a question or instruction for the Knowledge Base Assistant.");
				return false;
			}

			void (async () => {
				try {
					const session = await createGeneralSession.mutateAsync();
					router.push(`/dashboard/ingest/chat?session_id=${session.id}&q=${encodeURIComponent(value.trim())}`);
				} catch {
					router.push(`/dashboard/ingest/chat?q=${encodeURIComponent(value.trim())}`);
				}
			})();
			return;
		}

		// Normal Ingestion Flow
		if (files.length === 0) {
			setErrorMsg("Please attach at least one file to ingest.");
			return false;
		}

		const formData = new FormData();
		if (value && value.trim()) {
			formData.append("prompt", value.trim());
		}

		const isValidProject = selectedProjectId !== "none" && projects.some((p) => p.id === selectedProjectId);
		const targetProject = isValidProject ? selectedProjectId : null;
		if (targetProject) {
			formData.append("project_id", targetProject);
		}

		files.forEach((file) => {
			formData.append("file", file);
		});

		uploadMutation.mutate(formData, {
			onSuccess: (data: { batch_id?: string; upload_batch_id?: string; documents?: { knowledge_id: string }[] }) => {
				const batchId = data.batch_id || data.upload_batch_id;
				if (batchId) {
					router.push(`/dashboard/knowledge/batch/${batchId}`);
				} else if (data.documents && data.documents.length > 0) {
					router.push(`/dashboard/knowledge/${data.documents[0].knowledge_id}`);
				} else if (targetProject) {
					router.push(`/dashboard/knowledge/project/${targetProject}`);
				} else {
					router.push("/dashboard/knowledge");
				}
			},
		});
	};

	return (
		<div className="flex flex-col max-w-2xl mx-auto min-h-full w-full pt-10 pb-10 px-4">
			{/* Header */}
			<div className="flex flex-col items-center text-center space-y-2 mb-8">
				<div className="flex aspect-square size-12 items-center justify-center rounded-md bg-blue-50 text-blue-500">
					<RiRobot2Line className="size-6" />
				</div>
				<div className="space-y-1">
					<h1 className="text-xl font-semibold text-foreground">
						{isGeneralMode ? "Knowledge Base Assistant" : "Expand Knowledge Base"}
					</h1>
					<p className="text-sm text-muted-foreground max-w-95 leading-relaxed">
						{isGeneralMode
							? "Search and explore existing knowledge entries by asking questions via prompt."
							: "Upload product, treatment, or brochure documents to train the AI assistant."}
					</p>
				</div>
			</div>

			{/* Ingestion Quota Warning Banner (Only displayed in Ingest mode when approaching limit) */}
			{!isGeneralMode && quota && (quota.exceeded || quota.warning) && (
				<div className="mb-5 w-full">
					{quota.exceeded ? (
						<div className="flex items-start gap-3 p-3.5 rounded-lg border border-amber-300 bg-white text-xs">
							<RiAlertLine className="size-4 text-amber-600 shrink-0 mt-0.5" />
							<div className="flex flex-col gap-0.5">
								<span className="font-semibold text-zinc-900">Monthly Ingestion Limit Reached ({quota.percentage}%)</span>
								<span className="text-zinc-600">
									Used {quota.tokens_used.toLocaleString()} of {quota.token_limit.toLocaleString()} tokens. Ingestion will proceed, but threshold can be adjusted in Configuration.
								</span>
							</div>
						</div>
					) : (
						<div className="flex items-start gap-3 p-3.5 rounded-lg border border-amber-300 bg-white text-xs">
							<RiAlertLine className="size-4 text-amber-600 shrink-0 mt-0.5" />
							<div className="flex flex-col gap-0.5">
								<span className="font-semibold text-zinc-900">Monthly Ingestion Near Limit</span>
								<span className="text-zinc-600">
									{quota.tokens_used.toLocaleString()} of {quota.token_limit.toLocaleString()} tokens used ({quota.percentage}%).
								</span>
							</div>
						</div>
					)}
				</div>
			)}

			{/* Shortcuts */}
			{!isGeneralMode && (
				<div className="grid grid-cols-2 gap-3 w-full mb-4 shrink-0">
					<button
						type="button"
						onClick={() =>
							setPromptValue(
								"Analyze all uploaded documents and treat them as a unified knowledge base. Identify key information and cross-document relationships while ensuring that all findings remain strictly grounded in the provided sources. If the source knowledge is primarily in Indonesian, generate the response in Indonesian."
							)
						}
						className="flex flex-col items-start p-3 text-left rounded-xl border border-zinc-200/70 bg-white hover:border-zinc-300 hover:bg-zinc-50/60 transition-all cursor-pointer shadow-none"
					>
						<RiGitRepositoryLine className="size-4 text-zinc-950 mb-1.5" />
						<h3 className="font-semibold text-xs text-zinc-950 mb-0.5">Unified Knowledge Analysis</h3>
						<p className="text-[11px] leading-tight text-zinc-600 line-clamp-2">
							Analyze all uploaded documents and treat them as a unified knowledge base...
						</p>
					</button>
					<button
						type="button"
						onClick={() =>
							setPromptValue(
								"Review all uploaded files and map key entities, topics, and relationships across documents. Clearly distinguish between available information and information that is not provided in the knowledge base. If the source knowledge is primarily in Indonesian, generate the response in Indonesian."
							)
						}
						className="flex flex-col items-start p-3 text-left rounded-xl border border-zinc-200/70 bg-white hover:border-zinc-300 hover:bg-zinc-50/60 transition-all cursor-pointer shadow-none"
					>
						<RiGitMergeLine className="size-4 text-zinc-950 mb-1.5" />
						<h3 className="font-semibold text-xs text-zinc-950 mb-0.5">Entity & Topic Mapping</h3>
						<p className="text-[11px] leading-tight text-zinc-600 line-clamp-2">
							Review all uploaded files and map key entities, topics, and relationships across documents...
						</p>
					</button>
				</div>
			)}

			{/* Prompt Input */}
			<div className="shrink-0 mt-4 flex flex-col items-center relative">
				<div className="w-full">
					<PromptInput
						key={mode}
						autoFocus
						value={promptValue}
						onValueChange={setPromptValue}
						minRows={5}
						onSend={handleSend}
						showAttachButton={!isGeneralMode}
						showAttachText={!isGeneralMode}
						attachText="Add files"
						placeholder={
							isGeneralMode
								? "Ask about the knowledge..."
								: undefined
						}
						disabled={uploadMutation.isPending}
						isLoading={uploadMutation.isPending}
					/>
				</div>

				{errorMsg && (
					<div className="w-full mt-2 flex items-center text-[13px] font-medium text-amber-600 bg-amber-50 border border-amber-200/80 rounded-lg p-2.5">
						<RiAlertLine className="size-4 mr-1.5 shrink-0" />
						{errorMsg}
					</div>
				)}

				{/* Mode Switch & Controls below prompt input */}
				<div className="w-full flex flex-wrap items-center justify-between gap-3 mt-3 px-0.5">
					{/* Toggle Switch */}
					<div className="flex items-center gap-2">
						<Switch
							id="general-mode-toggle"
							checked={isGeneralMode}
							onCheckedChange={(checked) => {
								setMode(checked ? "general" : "ingest");
								setErrorMsg(null);
							}}
							disabled={uploadMutation.isPending}
						/>
						<label
							htmlFor="general-mode-toggle"
							className="text-xs font-medium text-zinc-700 cursor-pointer select-none"
						>
							{isGeneralMode ? "General Assistant Mode" : "File Ingestion Mode"}
						</label>
					</div>

					{/* Right Side: Project selector only when navigated from Project detail page, or helper for General */}
					{!isGeneralMode && Boolean(projectId && projectId !== "none") ? (
						<div className="flex items-center gap-2 max-w-full">
							<span className="text-xs text-zinc-500 font-medium shrink-0">Project:</span>
							<Select
								value={selectedProjectId}
								onValueChange={(val) => setSelectedProjectId(val ?? "none")}
								disabled={uploadMutation.isPending}
							>
								<SelectTrigger className="h-7.5 text-xs border border-zinc-200 bg-white text-zinc-700 rounded-md px-2.5 min-w-36 max-w-56 sm:max-w-72 shadow-none hover:border-zinc-300 transition-colors">
									<SelectValue placeholder="Select Project" className="truncate">
										{selectedProjectName}
									</SelectValue>
								</SelectTrigger>
								<SelectContent align="end" alignItemWithTrigger={false} sideOffset={4} className="bg-white max-w-xs">
									<SelectItem value="none">
										<span className="truncate">No Project</span>
									</SelectItem>
									{projects.map((p) => (
										<SelectItem key={p.id} value={p.id}>
											<span className="truncate" title={p.name}>{p.name}</span>
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>
					) : isGeneralMode ? (
						<div className="flex items-center gap-1.5 text-xs text-zinc-600">
							<span>No files needed</span>
						</div>
					) : null}
				</div>

				{/* Loading Overlays */}
				{uploadMutation.isPending && (
					<div className="absolute inset-0 bg-white/50 flex items-center justify-center rounded-xl z-10 backdrop-blur-sm">
						<span className="text-sm font-medium text-blue-600">Uploading documents...</span>
					</div>
				)}

				{!isGeneralMode && (
					<div className="mt-4 px-3.5 py-1.5 w-fit mx-auto border border-zinc-200/60 rounded-full flex items-center justify-center text-[11px] text-zinc-600 bg-zinc-50/50">
						<RiFileTextLine className="size-3 mr-1.5 text-zinc-600" />
						Supports PDF, DOCX, XLSX, TXT, JPG, and PNG
					</div>
				)}
			</div>
		</div>
	);
}

export default function IngestPage() {
	return (
		<Suspense fallback={<div className="p-8 text-center text-sm text-gray-500">Loading ingestion...</div>}>
			<IngestContent />
		</Suspense>
	);
}
