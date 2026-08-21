"use client";

import { Badge } from "@/components/ui/badge";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { KnowledgeResponse } from "../../api/types";
import { cn } from "@/lib/utils";
import {
	RiArrowDownSLine,
	RiFileListLine,
} from "@remixicon/react";
import { useEffect, useRef } from "react";

interface BatchDocumentTabsProps {
	documents: KnowledgeResponse[];
	activeId: string;
	onSelectDoc: (id: string) => void;
}

export function BatchDocumentTabs({
	documents,
	activeId,
	onSelectDoc,
}: BatchDocumentTabsProps) {
	const scrollContainerRef = useRef<HTMLDivElement>(null);

	// Auto-scroll active tab into view
	useEffect(() => {
		const el = scrollContainerRef.current;
		if (!el) return;
		const activeBtn = el.querySelector(`[data-tab-id="${activeId}"]`) as HTMLElement | null;
		if (activeBtn) {
			activeBtn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
		}
	}, [activeId]);

	const activeIndex = documents.findIndex((d) => d.id === activeId);

	return (
		<div className="flex flex-col gap-2 w-full min-w-0 max-w-full">
			{/* Sub-header with document count and dropdown picker */}
			<div className="flex items-center justify-between gap-2 w-full min-w-0">
				<div className="flex items-center gap-2 min-w-0">
					<h4 className="text-xs font-semibold text-blue-900/80 uppercase tracking-wider truncate">
						Documents in this batch ({documents.length})
					</h4>
					<span className="text-xs text-zinc-400 font-normal shrink-0">
						• Viewing {activeIndex + 1} of {documents.length}
					</span>
				</div>

				{/* Quick Document Picker Dropdown */}
				<DropdownMenu>
					<DropdownMenuTrigger className="inline-flex items-center justify-center h-7 text-xs font-medium gap-1.5 text-zinc-700 bg-white hover:bg-zinc-50 border border-zinc-200 px-2.5 rounded-lg cursor-pointer transition-colors shadow-none shrink-0">
						<RiFileListLine className="size-3.5 text-blue-600" />
						<span>All Documents ({documents.length})</span>
						<RiArrowDownSLine className="size-3.5 text-zinc-400" />
					</DropdownMenuTrigger>
					<DropdownMenuContent align="end" className="w-72 max-h-80 overflow-y-auto rounded-lg border border-zinc-200 p-1.5 shadow-none">
						{documents.map((doc, idx) => (
							<DropdownMenuItem
								key={doc.id}
								onClick={() => onSelectDoc(doc.id)}
								className={cn(
									"flex items-center justify-between gap-2 text-xs py-2 px-2.5 rounded-lg cursor-pointer transition-colors",
									doc.id === activeId ? "bg-blue-50 text-blue-900 font-medium" : "hover:bg-zinc-50"
								)}
							>
								<div className="flex items-center gap-2 min-w-0 flex-1">
									<span className="text-[11px] text-zinc-400 font-mono w-4 shrink-0">
										{idx + 1}.
									</span>
									<span className="truncate" title={doc.title || doc.file_name}>
										{doc.title || doc.file_name}
									</span>
								</div>
								<div className="shrink-0">
									{doc.status === "PROCESSING" && (
										<Badge className="bg-blue-50 text-blue-700 border-blue-200 text-[10px] px-1.5 py-0 rounded-lg shadow-none">
											Processing
										</Badge>
									)}
									{doc.status === "PENDING" && (
										<Badge className="bg-amber-50 text-amber-700 border-amber-200 text-[10px] px-1.5 py-0 rounded-lg shadow-none">
											Review
										</Badge>
									)}
									{doc.status === "APPROVED" && (
										<Badge className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[10px] px-1.5 py-0 rounded-lg shadow-none">
											Approved
										</Badge>
									)}
								</div>
							</DropdownMenuItem>
						))}
					</DropdownMenuContent>
				</DropdownMenu>
			</div>

			{/* Scrollable Tabs Bar */}
			<div
				ref={scrollContainerRef}
				className="w-full min-w-0 max-w-full overflow-x-auto overflow-y-hidden scroll-smooth pb-1.5 [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-track]:bg-zinc-100/80 [&::-webkit-scrollbar-track]:rounded-full [&::-webkit-scrollbar-thumb]:bg-zinc-300 [&::-webkit-scrollbar-thumb]:rounded-full hover:[&::-webkit-scrollbar-thumb]:bg-zinc-400"
			>
				<Tabs value={activeId} onValueChange={onSelectDoc} className="w-full min-w-0 max-w-full">
					<TabsList
						variant="line"
						className="inline-flex w-max min-w-0 justify-start border-none pb-0 gap-2 bg-transparent"
					>
						{documents.map((tabDoc, tabIndex) => (
							<TabsTrigger
								key={tabDoc.id}
								value={tabDoc.id}
								data-tab-id={tabDoc.id}
								title={tabDoc.title || `Document ${tabIndex + 1}`}
								className="w-48 shrink-0 relative inline-flex items-center justify-between font-medium text-xs text-blue-900/60 hover:text-blue-600 data-active:text-blue-600 data-active:after:bg-blue-600 px-2.5 py-1.5 transition-all cursor-pointer"
							>
								<span className="truncate min-w-0 flex-1 text-left">
									{tabDoc.title || `Document ${tabIndex + 1}`}
								</span>
								{tabDoc.status === "PROCESSING" && (
									<span
										className="size-2 rounded-full bg-blue-500 animate-pulse shrink-0 ml-1.5"
										title="Processing"
									/>
								)}
								{tabDoc.status === "PENDING" && (
									<span
										className="size-2 rounded-full bg-amber-500 shrink-0 ml-1.5"
										title="On Review"
									/>
								)}
								{tabDoc.status === "APPROVED" && (
									<span
										className="size-2 rounded-full bg-emerald-500 shrink-0 ml-1.5"
										title="Approved"
									/>
								)}
							</TabsTrigger>
						))}
					</TabsList>
				</Tabs>
			</div>
		</div>
	);
}
