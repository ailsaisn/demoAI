"use client";

import { useState } from "react";
import { KnowledgeSummary } from "@/components/shared/knowledge/knowledge-summary";
import { ProjectsTable } from "./components/projects-table";
import { KnowledgeTable } from "@/components/shared/knowledge/knowledge-table";
import { SearchBar } from "@/components/shared/search-bar";

export default function KnowledgePage() {
	const [searchQuery, setSearchQuery] = useState("");

	return (
		<div className="flex flex-col h-full gap-6 p-6">
			{/* Overview Summary Cards */}
			<KnowledgeSummary />

			{/* Single Search Bar */}
			<div className="w-full">
				<SearchBar
					containerClassName="max-w-md w-full sm:w-80"
					value={searchQuery}
					onChange={(e) => setSearchQuery(e.target.value)}
					placeholder="Search for project or knowledge..."
				/>
			</div>

			{/* Section 1: Projects Table */}
			<ProjectsTable searchQuery={searchQuery} />

			{/* Section 2: All Knowledge Base Table */}
			<KnowledgeTable searchQuery={searchQuery} />
		</div>
	);
}
