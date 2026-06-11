import Image from "next/image"

export function AxolotlMark({ className }: { className?: string }) {
  return (
    <div className={`relative overflow-hidden ${className}`}>
      <Image
        src="/Axolotl(without-bg).png"
        alt="Axolotl Logo"
        fill
        className="object-contain"
        priority
      />
    </div>
  )
}
