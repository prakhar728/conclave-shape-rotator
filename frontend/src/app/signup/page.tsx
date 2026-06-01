/**
 * /signup — exists so marketing/landing links don't 404, but the OTP flow
 * at /login already creates the account on first verify (per BUILD_DOC §10.2
 * + auth/routes.py's upsert_user_by_supabase). One door, two labels.
 */
import { redirect } from "next/navigation";

export default function SignupPage() {
  redirect("/login");
}
