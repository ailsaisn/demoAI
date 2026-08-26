"use client";

import { LoginForm } from "./components/login-form";
import { Suspense } from "react";

export default function LoginPage() {
	return (
		<div className="flex min-h-svh w-full items-center justify-center p-4 bg-white">
			<div className="w-full max-w-100 rounded-lg border border-gray-200 bg-white p-6 shadow-xs">
				<Suspense fallback={<div className="text-center py-4">Loading...</div>}>
					<LoginForm />
				</Suspense>
			</div>
		</div>
	);
}
