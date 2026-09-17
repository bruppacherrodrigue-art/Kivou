import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { useLocation } from 'react-router-dom'
import { AppRoutes } from '../App'
import { ME, callsTo, mockApi, renderApp } from '../test/harness'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function Location() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

test('prefills the invitation email, claims the account, then returns to the signal', async () => {
  const temporary = {
    ...ME,
    email: 'landing+abc@landing.kivou.invalid',
    account_display_name: 'Compte à confirmer',
    temporary_access: true,
    claim_email: 'claire@acme.test',
  }
  mockApi({
    'POST /auth/claim-access': {
      body: { ...temporary, email: temporary.claim_email, account_display_name: 'Acme', temporary_access: false, claim_email: null },
    },
  })
  renderApp(<><AppRoutes /><Location /></>, {
    route: { pathname: '/app/create-access', state: { returnTo: '/app/signals/sig_1' } },
    session: { status: 'authenticated', me: temporary },
  })

  expect(screen.getByLabelText('Adresse e-mail professionnelle')).toHaveValue('claire@acme.test')
  expect(screen.getByLabelText('Adresse e-mail professionnelle')).toHaveAttribute('readonly')
  await userEvent.type(screen.getByLabelText('Créer mon mot de passe'), 'une-phrase-secrete')
  await userEvent.type(screen.getByLabelText('Confirmer le mot de passe'), 'une-phrase-secrete')
  await userEvent.click(screen.getByRole('button', { name: 'Créer mon accès' }))

  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals/sig_1'))
  expect(callsTo('/auth/claim-access')).toHaveLength(1)
  expect(callsTo('/auth/claim-access')[0].body).toEqual({ password: 'une-phrase-secrete' })
})

test('asks a landing visitor for a real email before claiming the account', async () => {
  const temporary = {
    ...ME,
    email: 'landing+abc@landing.kivou.invalid',
    account_display_name: 'Compte à confirmer',
    temporary_access: true,
    claim_email: null,
  }
  mockApi({
    'POST /auth/claim-access': {
      body: { ...temporary, email: 'claire@acme.test', account_display_name: 'Acme', temporary_access: false },
    },
  })
  renderApp(<><AppRoutes /><Location /></>, {
    route: { pathname: '/app/create-access', state: { returnTo: '/app/signals/sig_1' } },
    session: { status: 'authenticated', me: temporary },
  })

  const email = screen.getByLabelText('Adresse e-mail professionnelle')
  const submit = screen.getByRole('button', { name: 'Créer mon accès' })
  expect(email).toHaveValue('')
  expect(email).not.toHaveAttribute('readonly')
  expect(email).toBeRequired()
  expect(submit).toBeDisabled()

  await userEvent.type(email, 'adresse-invalide')
  await userEvent.type(screen.getByLabelText('Créer mon mot de passe'), 'une-phrase-secrete')
  await userEvent.type(screen.getByLabelText('Confirmer le mot de passe'), 'une-phrase-secrete')
  expect(submit).toBeDisabled()

  await userEvent.clear(email)
  await userEvent.type(email, 'claire@acme.test')
  expect(submit).toBeEnabled()
  await userEvent.click(submit)

  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals/sig_1'))
  expect(callsTo('/auth/claim-access')).toHaveLength(1)
  expect(callsTo('/auth/claim-access')[0].body).toEqual({
    password: 'une-phrase-secrete',
    email: 'claire@acme.test',
  })
})
