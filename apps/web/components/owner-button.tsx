"use client";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useRole } from "@/lib/queries";

type Props = React.ComponentProps<typeof Button> & { reason?: string };

/** A button that only the workspace owner can use; viewers see it disabled with an explanation. */
export function OwnerButton({ reason = "Only the workspace owner can do this.", disabled, ...props }: Props) {
  const { isOwner, loading } = useRole();
  if (isOwner || loading) return <Button disabled={disabled || loading} {...props} />;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex">
          <Button {...props} disabled aria-disabled />
        </span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}
