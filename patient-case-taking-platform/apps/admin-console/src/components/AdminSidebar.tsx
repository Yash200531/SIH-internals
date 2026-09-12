"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/users", label: "Users" },
  { href: "/roles", label: "Roles" },
  { href: "/facilities", label: "Facilities" },
  { href: "/audit", label: "Audit" },
  { href: "/settings", label: "Settings" },
];

export function AdminSidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 w-60 bg-midnight-light border-r border-midnight-border flex flex-col">
      <div className="h-16 flex items-center px-6 border-b border-midnight-border">
        <span className="text-lg font-bold text-accent">MediKiosk Admin</span>
      </div>
      <nav className="flex-1 py-4 space-y-1 px-3">
        {links.map((link) => {
          const active =
            link.href === "/"
              ? pathname === "/"
              : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`block px-3 py-2 rounded text-sm transition-colors ${
                active
                  ? "bg-accent/10 text-accent"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
      <div className="p-4 border-t border-midnight-border text-xs text-slate-500">
        v0.1.0
      </div>
    </aside>
  );
}
