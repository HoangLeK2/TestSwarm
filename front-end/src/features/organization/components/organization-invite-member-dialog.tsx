'use client';

import { useState } from 'react';
import { UserPlus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { z } from 'zod';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useInviteOrganizationMember } from '../hooks/use-organization-members';
import { formatOrgMemberInviteError } from '../lib/format-org-invite-error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';

type Props = {
  trigger?: React.ReactNode;
};

type InviteForm = {
  email: string;
  role: 'member' | 'supervisor';
};

export function OrganizationInviteMemberDialog({ trigger }: Props) {
  const t = useTranslations('organization.memberManagement');
  const tCommon = useTranslations('common');
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error, reset } = useInviteOrganizationMember();

  const schema = z.object({
    email: z.string().email(t('invalidEmail')),
    role: z.enum(['member', 'supervisor'])
  });

  const {
    register,
    handleSubmit,
    reset: resetForm,
    setValue,
    watch,
    formState: { errors }
  } = useForm<InviteForm>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', role: 'member' }
  });

  const inviteRole = watch('role');

  const onSubmit = handleSubmit((data) => {
    const email = data.email.trim();
    mutate(
      { email, role: data.role },
      {
        onSuccess: (result) => {
          if (result.emailSent) {
            toast.success(
              result.existingUser
                ? t('inviteSentExisting', { email })
                : t('inviteSentNew', { email })
            );
          } else {
            toast.warning(t('inviteEmailNotSent', { email }));
          }
          resetForm();
          reset();
          setOpen(false);
        },
        onError: (err) => {
          toast.error(
            formatOrgMemberInviteError(err, t, t('inviteFailed', { email }))
          );
        }
      }
    );
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          resetForm();
          reset();
        }
      }}
    >
      <DialogTrigger asChild>
        {trigger ?? (
          <Button type='button'>
            <UserPlus className='mr-2 size-4' />
            {t('inviteMember')}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('inviteNewMember')}</DialogTitle>
          <DialogDescription>{t('inviteDescription')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className='space-y-4'>
          <div className='space-y-2'>
            <Label htmlFor='invite-email'>{t('emailAddress')}</Label>
            <Input
              id='invite-email'
              type='email'
              autoComplete='email'
              placeholder={t('enterEmailAddress')}
              {...register('email')}
            />
            {errors.email ? (
              <p className='text-xs text-destructive'>{errors.email.message}</p>
            ) : null}
          </div>
          <div className='space-y-2'>
            <Label htmlFor='invite-role'>{t('role')}</Label>
            <Select
              value={inviteRole}
              onValueChange={(value) =>
                setValue('role', value as InviteForm['role'], {
                  shouldValidate: true
                })
              }
            >
              <SelectTrigger id='invite-role' className='w-full'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='member'>{t('staff')}</SelectItem>
                <SelectItem value='supervisor'>{t('supervisor')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error ? (
            <p className='text-xs text-destructive'>
              {formatOrgMemberInviteError(
                error,
                t,
                t('inviteFailed', { email: '' })
              )}
            </p>
          ) : null}
          <div className='flex justify-end gap-2'>
            <Button
              type='button'
              variant='outline'
              onClick={() => setOpen(false)}
              disabled={isPending}
            >
              {tCommon('cancel')}
            </Button>
            <Button type='submit' disabled={isPending}>
              {isPending ? t('inviting') : t('sendInvite')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
