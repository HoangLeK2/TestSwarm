export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className='relative flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-background to-muted'>
      <div className='pointer-events-none absolute inset-0 opacity-60'>
        <div className='absolute -top-32 left-[-10%] h-72 w-72 rounded-full bg-primary/10 blur-3xl' />
        <div className='absolute bottom-[-20%] right-[-10%] h-80 w-80 rounded-full bg-sky-500/10 blur-3xl' />
      </div>

      <div className='relative z-10 w-full max-w-md px-4 py-10 sm:px-6 sm:py-12 md:px-0'>
        {children}
      </div>
    </div>
  );
}
