"use client";

import { useLogin } from "@/app/login/hooks/use-login";
import { Button } from "@/components/ui/button";
import {
	Field,
	FieldContent,
	FieldError,
	FieldGroup,
	FieldLabel,
	FieldTitle,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { cn, getErrorMessage } from "@/lib/utils";
import {
	RiErrorWarningLine,
	RiEyeLine,
	RiEyeOffLine,
	RiLoader4Line,
	RiRobot2Line,
} from "@remixicon/react";
import { useForm } from "@tanstack/react-form";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { loginSchema, type LoginValues } from "./login-schema";

export function LoginForm({ className, ...props }: React.ComponentProps<"form">) {
	const router = useRouter();
	const searchParams = useSearchParams();
	const [loginError, setLoginError] = useState<string | null>(null);
	const [showPassword, setShowPassword] = useState(false);
	const { mutate: login, isPending } = useLogin();

	useEffect(() => {
		if (typeof window !== "undefined") {
			sessionStorage.removeItem("is_logging_out");
		}
	}, []);

	const form = useForm({
		defaultValues: {
			email: "",
			password: "",
		} as LoginValues,
		validators: {
			onChange: loginSchema,
		},
		onSubmit: async ({ value, formApi }) => {
			setLoginError(null);

			const credentials = new URLSearchParams();
			credentials.append("username", value.email);
			credentials.append("password", value.password);

			await new Promise((resolve) => setTimeout(resolve, 800));

			login(credentials, {
				onSuccess: ({ userProfile }) => {
					const fromParam = searchParams.get("from");
					let target = "/dashboard/knowledge";

					if (fromParam && fromParam.startsWith("/") && !fromParam.startsWith("/login")) {
						target = fromParam;
					}

					router.push(target);

					setTimeout(() => {
						toast.success(`Welcome, ${userProfile.name}!`);
					}, 300);
				},
				onError: (err) => {
					setLoginError(getErrorMessage(err, "An error occurred during login. Please try again."));
					formApi.reset();
				},
			});
		},
	});

	const reason = searchParams.get("reason");
	const reasonMessage =
		reason === "idle"
			? "You were logged out due to inactivity."
			: reason === "session_expired"
				? "Your session has expired. Please log in again."
				: null;

	useEffect(() => {
		if (reasonMessage) {
			toast.warning(reasonMessage);
		}
	}, [reasonMessage]);

	return (
		<form
			onSubmit={(e) => {
				e.preventDefault();
				e.stopPropagation();
				void form.handleSubmit();
			}}
			className={cn("flex flex-col gap-6", className)}
			{...props}
		>
			<FieldGroup>
				<div className="flex flex-col items-center text-center">
					<div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-50">
						<RiRobot2Line className="h-7 w-7 text-blue-600" />
					</div>
					<h1 className="mb-1 text-xl font-semibold text-foreground">Hello, welcome back</h1>
					<p className="text-sm text-muted-foreground">
						Sign in to manage conversations, knowledge, and chatbot performance.
					</p>
				</div>

				{reasonMessage && !loginError && (
					<div className="flex items-center gap-3 text-sm font-medium text-amber-700 bg-amber-50 dark:bg-amber-950/40 dark:text-amber-300 p-3 rounded-lg mb-2 border border-amber-200 dark:border-amber-800">
						<RiErrorWarningLine className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
						<span className="leading-tight">{reasonMessage}</span>
					</div>
				)}

				{loginError && (
					<div className="flex items-center gap-3 text-sm font-medium text-destructive bg-destructive/10 p-3 rounded-lg mb-2">
						<RiErrorWarningLine className="h-5 w-5 shrink-0" />
						<span className="leading-tight">{loginError}</span>
					</div>
				)}

				<form.Field name="email">
					{(field) => {
						const isInvalid = field.state.meta.errors && field.state.meta.errors.length > 0;
						return (
							<Field data-invalid={isInvalid}>
								<FieldLabel htmlFor="email">
									<FieldTitle className="text-sm font-normal text-neutral-900">Email</FieldTitle>
								</FieldLabel>
								<FieldContent>
									<div className="relative">
										<Input
											name={field.name}
											id="email"
											type="email"
											placeholder="e.g. johndoe@gmail.com"
											value={field.state.value}
											onChange={(e) => field.handleChange(e.target.value)}
											onBlur={field.handleBlur}
											disabled={isPending}
											aria-invalid={isInvalid}
											autoComplete="username"
											className="border-gray-200 bg-white focus-visible:ring-blue-500"
										/>
									</div>
								</FieldContent>
								{isInvalid && (
									<FieldError errors={field.state.meta.errors as Array<{ message?: string }>} />
								)}
							</Field>
						);
					}}
				</form.Field>

				<form.Field name="password">
					{(field) => {
						const isInvalid = field.state.meta.errors && field.state.meta.errors.length > 0;
						return (
							<Field data-invalid={isInvalid}>
								<FieldLabel htmlFor="password">
									<FieldTitle className="text-sm font-normal text-neutral-900">Password</FieldTitle>
								</FieldLabel>
								<FieldContent>
									<div className="relative">
										<Input
											name={field.name}
											id="password"
											type={showPassword ? "text" : "password"}
											placeholder="••••••••"
											value={field.state.value}
											onChange={(e) => field.handleChange(e.target.value)}
											onBlur={field.handleBlur}
											disabled={isPending}
											aria-invalid={isInvalid}
											autoComplete="current-password"
											className="border-gray-200 bg-white focus-visible:ring-blue-500 pr-10"
										/>
										<Button
											type="button"
											variant="ghost"
											size="icon"
											className="absolute right-0 top-0 h-full px-3 py-2 text-zinc-600 hover:text-zinc-900 hover:bg-transparent"
											onClick={() => setShowPassword(!showPassword)}
										>
											{showPassword ? (
												<RiEyeOffLine className="h-4 w-4" />
											) : (
												<RiEyeLine className="h-4 w-4" />
											)}
										</Button>
									</div>
								</FieldContent>
								{isInvalid && (
									<FieldError errors={field.state.meta.errors as Array<{ message?: string }>} />
								)}
							</Field>
						);
					}}
				</form.Field>

				<form.Subscribe selector={(state) => [state.isSubmitting]}>
					{([isSubmitting]) => (
						<Field className="pt-2">
							<Button
								type="submit"
								disabled={isPending || isSubmitting}
								className="w-full bg-blue-500 hover:bg-blue-600 text-white font-medium h-10 rounded-lg"
							>
								{isPending || isSubmitting ? (
									<>
										<RiLoader4Line className="mr-2 h-4 w-4 animate-spin shrink-0" />
										Logging in...
									</>
								) : (
									"Login"
								)}
							</Button>
						</Field>
					)}
				</form.Subscribe>
			</FieldGroup>
		</form>
	);
}
