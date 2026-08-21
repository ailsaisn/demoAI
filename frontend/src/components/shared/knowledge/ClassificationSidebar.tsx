import { KnowledgeResponse } from "@/app/dashboard/knowledge/api/types";
import { useApproveKnowledge, useEditKnowledge } from "@/app/dashboard/knowledge/hooks/use-knowledge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { RiCheckLine, RiLoader4Line } from "@remixicon/react";
import { useSession } from "@/hooks/use-session";
import { VisibilitySettings } from "@/app/dashboard/knowledge/api/types";
import { ConfirmationModal } from "./ConfirmationModal";
import { IngestSuccessModal } from "./IngestSuccessModal";
import { useState } from "react";
import { useRouter } from "next/navigation";

interface ClassificationSidebarProps {
	knowledge?: KnowledgeResponse;
	pendingCategories?: string[];
	pendingVisibilitySettings?: VisibilitySettings;
	pendingTitle?: string;
}

export function ClassificationSidebar({ knowledge, pendingCategories, pendingVisibilitySettings, pendingTitle }: ClassificationSidebarProps) {
	const router = useRouter();
	const approveKnowledge = useApproveKnowledge();
	const editKnowledge = useEditKnowledge();
	const { user } = useSession();
	const hasWriteAccess = user?.accesses?.includes("knowledge:write");
	const [isConfirmModalOpen, setIsConfirmModalOpen] = useState(false);
	const [isSuccessModalOpen, setIsSuccessModalOpen] = useState(false);

	if (!knowledge) return null;

	const handleApprove = async () => {
		if ((pendingCategories && pendingCategories.length > 0) || pendingVisibilitySettings || pendingTitle) {
			await editKnowledge.mutateAsync({ id: knowledge.id, data: { summary: knowledge.ai_summary || "", categories: pendingCategories || [], visibility_settings: pendingVisibilitySettings, title: pendingTitle }, hideToast: true });
		}
		await approveKnowledge.mutateAsync(knowledge.id);
		if (typeof window !== "undefined") {
			localStorage.removeItem(`chat_preview_${knowledge.id}`);
		}
		setIsSuccessModalOpen(true);
	};

	return (
		<>
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

				{/* Manual Approval Action Card when status is PENDING */}
				{knowledge.status === "PENDING" && hasWriteAccess && (
					<div className="flex items-center gap-2 shrink-0">
						<Button
							onClick={() => setIsConfirmModalOpen(true)}
							disabled={approveKnowledge.isPending || editKnowledge.isPending}
							className="bg-blue-600 hover:bg-blue-700 text-white gap-2 cursor-pointer shadow-none rounded-lg"
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

			{/* Save Knowledge / Approve Confirmation Modal */}
			<ConfirmationModal
				isOpen={isConfirmModalOpen}
				onOpenChange={setIsConfirmModalOpen}
				title="Save Knowledge?"
				description="Are you sure you want to save the changes of the  knowledge? If you confirm, it will be implemented into the chatbot."
				confirmText="Save Knowledge"
				cancelText="Cancel"
				isLoading={approveKnowledge.isPending || editKnowledge.isPending}
				onConfirm={handleApprove}
			/>

			{/* Knowledge Ingested Successfully Modal */}
			<IngestSuccessModal
				isOpen={isSuccessModalOpen}
				onOpenChange={setIsSuccessModalOpen}
				title="Knowledge Ingested Successfully"
				description="Now the knowledge that you uploaded and approved already added to the system"
				buttonText="View Knowledge"
				onAction={() => {
					router.push("/dashboard/knowledge");
				}}
			/>
		</>
	);
}
