import { motion } from 'framer-motion';

export function FadeInSide({
  children,
  animate = true
}: {
  children: React.ReactNode;
  animate?: boolean;
}) {
  return (
    <motion.div
      className='space-y-4'
      initial={{ opacity: 0, transform: 'translateX(-40px)' }}
      animate={animate ? { opacity: 1, transform: 'translateX(0)' } : {}}
      exit={animate ? { opacity: 0, transform: 'translateX(40px)' } : {}}
      transition={{
        duration: 0.3,
        ease: 'easeInOut',
        bounceDamping: 0.5,
        bounceStiffness: 100
      }}
    >
      {children}
    </motion.div>
  );
}
