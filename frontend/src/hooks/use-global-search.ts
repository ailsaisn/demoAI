import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { searchGlobal, UnifiedSearchResponse } from "@/app/dashboard/api/search";

export function useDebounce<T>(value: T, delay: number): T {
	const [debouncedValue, setDebouncedValue] = useState<T>(value);

	useEffect(() => {
		const timer = setTimeout(() => setDebouncedValue(value), delay);
		return () => clearTimeout(timer);
	}, [value, delay]);

	return debouncedValue;
}

export function useGlobalSearch(
	query: string,
	category: "all" | "knowledge" | "projects" | "categories" | "chats" = "all",
	debounceMs: number = 200,
) {
	const debouncedQuery = useDebounce(query, debounceMs);

	const queryResult = useQuery<UnifiedSearchResponse>({
		queryKey: ["global-search", debouncedQuery, category],
		queryFn: () => searchGlobal(debouncedQuery, category),
		enabled: debouncedQuery.trim().length > 0,
		staleTime: 1000 * 30,
	});

	return {
		...queryResult,
		isDebouncing: query !== debouncedQuery,
		debouncedQuery,
	};
}
