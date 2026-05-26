import { cn } from "@workspace/ui/lib/utils";
import {
  IconShieldLock,
  IconCloud,
  IconLock,
  IconEaseInOut,
  IconBrandGithub,
  IconCertificate,
  IconFingerprint,
  IconShieldCheck,
} from "@tabler/icons-react";

export function FeaturesSectionWithHoverEffects() {
  const features = [
    {
      title: "Hardware-Enforced Privacy",
      description:
        "Your data enters a Trusted Execution Environment. Not even the platform operator can read it.",
      icon: <IconShieldLock />,
    },
    {
      title: "Zero-Knowledge Outputs",
      description:
        "Only novelty scores and alignment flags exit the enclave. Raw content never leaves.",
      icon: <IconEaseInOut />,
    },
    {
      title: "Cryptographic Attestation",
      description:
        "Verify what code ran on your data. Every enclave is publicly auditable against its published measurement.",
      icon: <IconFingerprint />,
    },
    {
      title: "End-to-End TLS",
      description:
        "Connections terminate inside the TEE. No intermediary — not the network, not us — can intercept.",
      icon: <IconLock />,
    },
    {
      title: "Open Source Verified",
      description:
        "The enclave image matches the published Git SHA. Anyone can reproduce and verify the build.",
      icon: <IconBrandGithub />,
    },
    {
      title: "Signed Results",
      description:
        "Every output is signed with the enclave's hardware-bound private key. Tamper-proof by design.",
      icon: <IconCertificate />,
    },
    {
      title: "AI-Powered Insights",
      description:
        "Advanced AI skills process submissions together — novelty scoring, clustering, and criteria evaluation.",
      icon: <IconCloud />,
    },
    {
      title: "No Trust Required",
      description:
        "This isn't a policy promise. It's a cryptographic constraint — the enclave has no write path outside.",
      icon: <IconShieldCheck />,
    },
  ];
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 relative z-10 py-10 max-w-[980px] mx-auto">
      {features.map((feature, index) => (
        <Feature key={feature.title} {...feature} index={index} />
      ))}
    </div>
  );
}

const Feature = ({
  title,
  description,
  icon,
  index,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
  index: number;
}) => {
  return (
    <div
      className={cn(
        "flex flex-col lg:border-r py-10 relative group/feature border-[#d2d2d7]",
        (index === 0 || index === 4) && "lg:border-l border-[#d2d2d7]",
        index < 4 && "lg:border-b border-[#d2d2d7]"
      )}
    >
      {index < 4 && (
        <div className="opacity-0 group-hover/feature:opacity-100 transition duration-200 absolute inset-0 h-full w-full bg-gradient-to-t from-[#f5f5f7] to-transparent pointer-events-none" />
      )}
      {index >= 4 && (
        <div className="opacity-0 group-hover/feature:opacity-100 transition duration-200 absolute inset-0 h-full w-full bg-gradient-to-b from-[#f5f5f7] to-transparent pointer-events-none" />
      )}
      <div className="mb-4 relative z-10 px-10 text-[#6e6e73]">
        {icon}
      </div>
      <div className="text-lg font-bold mb-2 relative z-10 px-10">
        <div className="absolute left-0 inset-y-0 h-6 group-hover/feature:h-8 w-1 rounded-tr-full rounded-br-full bg-[#d2d2d7] group-hover/feature:bg-[#6e3ff3] transition-all duration-200 origin-center" />
        <span className="group-hover/feature:translate-x-2 transition duration-200 inline-block text-[#1d1d1f]">
          {title}
        </span>
      </div>
      <p className="text-sm text-[#6e6e73] max-w-xs relative z-10 px-10">
        {description}
      </p>
    </div>
  );
};
