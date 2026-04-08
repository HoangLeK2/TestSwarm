'use client';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useRegister } from '@/features/auth/hooks/use-register';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Link } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

const schema = z.object({
  name: z.string().min(2, 'Tên tối thiểu 2 ký tự'),
  email: z.string().email('Email không hợp lệ'),
  password: z.string().min(6, 'Mật khẩu tối thiểu 6 ký tự')
});
type FormData = z.infer<typeof schema>;

export default function SignUpPage() {
  const { mutate, isPending, error } = useRegister();
  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema)
  });

  return (
    <div className='flex min-h-screen items-center justify-center bg-background'>
      <div className='w-full max-w-sm space-y-6 rounded-xl border border-border bg-card p-8 shadow-sm'>
        <div className='space-y-1'>
          <h1 className='text-2xl font-semibold'>Đăng ký</h1>
          <p className='text-sm text-muted-foreground'>Tạo tài khoản Device Farm</p>
        </div>

        <form onSubmit={handleSubmit((d) => mutate(d))} className='space-y-4'>
          <div className='space-y-1'>
            <Label htmlFor='name'>Tên</Label>
            <Input id='name' placeholder='Nguyen Van A' {...register('name')} />
            {errors.name && <p className='text-xs text-destructive'>{errors.name.message}</p>}
          </div>

          <div className='space-y-1'>
            <Label htmlFor='email'>Email</Label>
            <Input id='email' type='email' placeholder='user@example.com' {...register('email')} />
            {errors.email && <p className='text-xs text-destructive'>{errors.email.message}</p>}
          </div>

          <div className='space-y-1'>
            <Label htmlFor='password'>Mật khẩu</Label>
            <Input id='password' type='password' placeholder='••••••••' {...register('password')} />
            {errors.password && <p className='text-xs text-destructive'>{errors.password.message}</p>}
          </div>

          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, 'Đăng ký thất bại')}
            </p>
          )}

          <Button type='submit' className='w-full' disabled={isPending}>
            {isPending ? 'Đang đăng ký…' : 'Đăng ký'}
          </Button>
        </form>

        <p className='text-center text-sm text-muted-foreground'>
          Đã có tài khoản?{' '}
          <Link href={ROUTES.AUTH.SIGN_IN} className='text-primary underline'>
            Đăng nhập
          </Link>
        </p>
      </div>
    </div>
  );
}
