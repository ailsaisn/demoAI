import { KnowledgeResponse } from "@/app/dashboard/knowledge/api/types";
import { useUpdateKnowledgeStatus, useApproveKnowledge, useEditKnowledge } from "@/app/dashboard/knowledge/hooks/use-knowledge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { RiCheckLine, RiCloseLine, RiLoader4Line } from "@remixicon/react";
import { useSession } from "@/hooks/use-session";
import { VisibilitySettings } from "@/app/dashboard/knowledge/api/types";

interface ClassificationSidebarProps {
	knowledge?: KnowledgeResponse;
	pendingCategories?: string[];
	pendingVisibilitySettings?: VisibilitySettings;
	pendingTitle?: string;
}

export function ClassificationSidebar({ knowledge, pendingCategories, pendingVisibilitySettings, pendingTitle }: ClassificationSidebarProps) {
	const updateStatus = useUpdateKnowledgeStatus();
	const approveKnowledge = useApproveKnowledge();
	const editKnowledge = useEditKnowledge();
	const { user } = useSession();
	const hasWriteAccess = user?.accesses?.includes("knowledge:write");

	if (!knowledge) return null;

	const handleApprove = async () => {
		if ((pendingCategories && pendingCategories.length > 0) || pendingVisibilitySettings || pendingTitle) {
			await editKnowledge.mutateAsync({ id: knowledge.id, data: { summary: knowledge.ai_summary || "", categories: pendingCategories || [], visibility_settings: pendingVisibilitySettings, title: pendingTitle }, hideToast: true });
		}
		approveKnowledge.mutate(knowledge.id);
		if (typeof window !== "undefined") {
			localStorage.removeItem(`chat_preview_${knowledge.id}`);
		}
	};

	const handleReject = () => {
		updateStatus.mutate({ id: knowledge.id, status: "REJECTED" });
	};

	return (
		<div className="flex flex-wrap sm:flex-nowrap items-center justify-between gap-6 w-full">
			{/* AI Confidence Score */}
			<div className="flex flex-col gap-2 w-full max-w-50">
				<div className="flex items-center gap-1.5 text-sm font-medium text-zinc-700">
					<span>AI Confidence Score:</span>
					<span className="text-blue-600">
						{knowledge.ai_confidence !== null && knowledge.ai_confidence !== undefined
							? `${Number(knowledge.ai_confidence)}%`
							: knowledge.status === "PROCESSING"
								? "Calculating..."
								: "—"}
					</span>
				</div>
				<Progress
					value={
						knowledge.ai_confidence !== null && knowledge.ai_confidence !== undefined
							? Number(knowledge.ai_confidence)
							: 0
					}
					className="h-2 w-full bg-blue-100"
				/>
			</div>

			{/* Manual Approval Action Card when status is PENDING or PROCESSING */}
			{knowledge.status === "PENDING" && hasWriteAccess && (
				<div className="flex items-center gap-2 shrink-0">
					<Button
						onClick={handleReject}
						disabled={updateStatus.isPending}
						variant="outline"
						className="text-red-600 hover:text-red-700 border-red-200 hover:bg-red-50 gap-2"
					>
						<RiCloseLine className="size-4" />
						Reject
					</Button>
					<Button
						onClick={handleApprove}
						disabled={approveKnowledge.isPending || editKnowledge.isPending}
						className="bg-blue-600 hover:bg-blue-700 text-white gap-2"
					>
						{approveKnowledge.isPending || editKnowledge.isPending ? (
							<>
								<RiLoader4Line className="size-4 animate-spin" />
								Indexing...
							</>
						) : (
							<>
								<RiCheckLine className="size-4" />
								Approve
							</>
						)}
					</Button>
				</div>
			)}
		</div>
	);
}
