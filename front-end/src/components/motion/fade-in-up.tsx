import { motion } from 'framer-motion';

export function FadeInUp({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      className='space-y-4'
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 16 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  );
}
